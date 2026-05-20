"""
Service de synchronisation des devis acceptés depuis Karlia.
Filtre automatiquement les devis dont l'opportunité est déjà marquée "Traité".
Après import, marque l'opportunité comme "Traité" dans Karlia.

Rate-limiting Karlia (quota 100 req/min) :
- Sleep configurable (settings.KARLIA_SYNC_SLEEP_SECONDS, défaut 1.2s) en tête
  de chaque itération du loop de sync, qui peut faire jusqu'à 4 appels Karlia.
- Retry automatique sur 429 (backoff 5s → 15s → 30s) dans `_get_with_retry`.
- Les erreurs HTTP autres que 429 (404, 5xx…) ne déclenchent pas de retry :
  elles sont loguées et la méthode renvoie None.

Historique : la sync du 2026-05-20 a importé 108 devis en rafale et atteint
le quota Karlia. Les `get_devis_detail()` ont été silencieusement avalés en
429, 106 commandes ont été créées avec pdf_url=None. Le rattrapage
(scripts/rattrapage_pdf_url.py) a corrigé l'incident; ce module embarque
maintenant la prévention. Diagnostic complet :
docs/DIAGNOSTIC_PDF_COMMANDES.md.
"""
import httpx
import asyncio
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Commande, CommandeLigne, Parametre

logger = logging.getLogger(__name__)

KARLIA_TYPE_DEVIS = 1
KARLIA_TYPE_BON_COMMANDE = 2  # documenté pour traçabilité, utilisé uniquement dans les logs/diagnostics
KARLIA_STATUS_DEVIS_ACCEPTE = 2
KARLIA_FIELD_TRAITE_ID = "66505"

# Backoffs successifs sur 429 (en secondes). 3 retries max avant abandon.
RATE_LIMIT_RETRY_BACKOFFS = [5, 15, 30]


class KarliaDevisService:
    def __init__(self):
        self.base_url = settings.KARLIA_API_URL.rstrip('/')
        self.api_key = self._get_api_key_from_db()

    def _get_api_key_from_db(self) -> str:
        db = SessionLocal()
        try:
            param = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
            return param.valeur if param and param.valeur else ""
        finally:
            db.close()

    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

    def _get_derniere_synchro(self, db: Session) -> Optional[datetime]:
        param = db.query(Parametre).filter(Parametre.cle == "derniere_synchro_devis").first()
        if param and param.valeur:
            try:
                return datetime.fromisoformat(param.valeur)
            except ValueError:
                return None
        return None

    def _set_derniere_synchro(self, db: Session, date_synchro: datetime):
        param = db.query(Parametre).filter(Parametre.cle == "derniere_synchro_devis").first()
        if param:
            param.valeur = date_synchro.isoformat()
        else:
            param = Parametre(cle="derniere_synchro_devis", valeur=date_synchro.isoformat())
            db.add(param)
        db.commit()

    # ─────────────────────────────────────────────────────────────────────────
    # Helper HTTP — retry 429 + backoff
    # ─────────────────────────────────────────────────────────────────────────

    async def _get_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: Optional[dict] = None,
        context: str = "",
    ) -> Optional[httpx.Response]:
        """
        GET Karlia avec retry automatique sur 429 (rate-limit).

        - 200            → renvoie la Response
        - 429            → backoff 5/15/30s puis retry (3 max), log warning à chaque tentative
        - 429 persistant → log error + None
        - 404 / autres   → log error + None (pas de retry)
        - erreur réseau  → retry avec même backoff que 429, puis log error + None

        Le caller appelle `.json()` sur la Response si nécessaire.
        """
        label = context or url
        for attempt in range(len(RATE_LIMIT_RETRY_BACKOFFS) + 1):
            try:
                response = await client.get(url, headers=self._get_headers(), params=params)
            except httpx.HTTPError as e:
                if attempt < len(RATE_LIMIT_RETRY_BACKOFFS):
                    wait = RATE_LIMIT_RETRY_BACKOFFS[attempt]
                    logger.warning(f"Karlia erreur réseau sur {label} : {e!r} - retry dans {wait}s")
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"Karlia erreur réseau persistante sur {label} : {e!r}")
                return None

            if response.status_code == 200:
                return response
            if response.status_code == 429:
                if attempt < len(RATE_LIMIT_RETRY_BACKOFFS):
                    wait = RATE_LIMIT_RETRY_BACKOFFS[attempt]
                    logger.warning(
                        f"Karlia 429 sur {label} (rate limit) - retry dans {wait}s "
                        f"(tentative {attempt + 1}/{len(RATE_LIMIT_RETRY_BACKOFFS)})"
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"Karlia 429 persistant après {len(RATE_LIMIT_RETRY_BACKOFFS)} retries sur {label}")
                return None
            # Autres status (404, 5xx…) : pas de retry, on remonte None
            logger.error(f"Karlia HTTP {response.status_code} sur {label} : {response.text[:200]}")
            return None
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # API Karlia — Documents (devis)
    # ─────────────────────────────────────────────────────────────────────────

    async def get_devis_acceptes(self, depuis_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Récupère tous les devis acceptés depuis Karlia, paginés."""
        devis_acceptes = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            offset = 0
            limit = 100
            while True:
                params = {
                    # NB: Karlia v2 attend `type` (pas `id_type` qui est silencieusement
                    # ignoré). Validé par test live le 2026-05-20 — voir commit message
                    # et fix/cleanup-bc-commandes pour le contexte.
                    "type": KARLIA_TYPE_DEVIS,
                    "id_status": KARLIA_STATUS_DEVIS_ACCEPTE,
                    "limit": limit,
                    "offset": offset,
                }
                if depuis_date:
                    params["update_date_min"] = depuis_date.strftime("%Y-%m-%d")

                response = await self._get_with_retry(
                    client,
                    f"{self.base_url}/documents",
                    params=params,
                    context=f"listing devis offset={offset}",
                )
                if response is None:
                    break
                data = response.json()
                documents = data.get("data", [])
                devis_acceptes.extend(documents)
                total = data.get("pagination", {}).get("total", 0)
                if len(devis_acceptes) >= total or len(documents) < limit:
                    break
                offset += limit
                await asyncio.sleep(0.8)

        return devis_acceptes

    async def get_devis_detail(self, document_id: int) -> Optional[Dict[str, Any]]:
        """Récupère le détail complet d'un devis (produits, PDF, etc.)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await self._get_with_retry(
                client,
                f"{self.base_url}/documents/{document_id}",
                context=f"detail devis {document_id}",
            )
            return response.json() if response is not None else None

    async def get_customer_detail(self, customer_id: int) -> Optional[Dict[str, Any]]:
        """Récupère les infos client depuis Karlia."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await self._get_with_retry(
                client,
                f"{self.base_url}/customers/{customer_id}",
                context=f"customer {customer_id}",
            )
            return response.json() if response is not None else None

    # ─────────────────────────────────────────────────────────────────────────
    # API Karlia — Opportunités (marquage "Traité")
    # ─────────────────────────────────────────────────────────────────────────

    async def _is_opportunity_traitee(self, client: httpx.AsyncClient, opportunity_id: str) -> bool:
        """Vérifie si une opportunité est déjà marquée 'Traité' dans Karlia."""
        response = await self._get_with_retry(
            client,
            f"{self.base_url}/opportunities/{opportunity_id}",
            context=f"opportunite {opportunity_id}",
        )
        if response is None:
            return False
        opp_data = response.json()
        custom_fields = opp_data.get("custom_fields_list", [])
        traite_field = next(
            (cf for cf in custom_fields if cf["id"] == KARLIA_FIELD_TRAITE_ID),
            None
        )
        return traite_field is not None and traite_field.get("value") == "1"

    async def _marquer_opportunity_traitee(self, client: httpx.AsyncClient, opportunity_id: str) -> bool:
        """Coche le custom field 'Traité' sur une opportunité Karlia."""
        try:
            response = await client.post(
                f"{self.base_url}/opportunities/{opportunity_id}/custom-fields/{KARLIA_FIELD_TRAITE_ID}",
                headers=self._get_headers(),
                json={"field_value": 1}
            )
            response.raise_for_status()
            logger.info(f"Opportunité {opportunity_id} marquée comme traitée")
            return True
        except httpx.HTTPError as e:
            logger.error(f"Erreur marquage opportunité {opportunity_id}: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # Utilitaires parsing
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_karlia_date(self, date_str: Optional[str]) -> Optional[date]:
        if not date_str:
            return None
        try:
            if "/" in date_str:
                return datetime.strptime(date_str, "%d/%m/%Y").date()
            return datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return None

    def _parse_tva(self, tva_value: Any) -> Optional[float]:
        if tva_value is None:
            return None
        tva_map = {"1": 20.0, "2": 10.0, "3": 5.5, "4": 0.0, 1: 20.0, 2: 10.0, 3: 5.5, 4: 0.0}
        if tva_value in tva_map:
            return tva_map[tva_value]
        try:
            return float(tva_value)
        except (ValueError, TypeError):
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Synchronisation principale
    # ─────────────────────────────────────────────────────────────────────────

    async def sync_devis_acceptes(self, db: Session, force_full: bool = False) -> Dict[str, Any]:
        """
        Synchronise les devis acceptés depuis Karlia.
        - Ignore les devis dont l'opportunité est déjà marquée 'Traité'
        - Après import d'un nouveau devis, marque l'opportunité comme 'Traité'
        - Rejette tout document dont id_type != KARLIA_TYPE_DEVIS (défense en profondeur)
        - Sleep settings.KARLIA_SYNC_SLEEP_SECONDS entre chaque itération pour
          rester sous le quota Karlia 100 req/min (chaque itération peut faire
          jusqu'à 4 appels API)
        """
        result = {
            "success": True,
            "nouveaux_devis": 0,
            "devis_mis_a_jour": 0,
            "devis_ignores": 0,
            "documents_rejetes_par_type": 0,
            "opportunites_marquees": 0,
            "pdf_url_renseigne": 0,
            "pdf_url_absent": 0,
            "erreurs": [],
            "message": ""
        }

        sleep_sec = settings.KARLIA_SYNC_SLEEP_SECONDS

        try:
            depuis_date = None if force_full else self._get_derniere_synchro(db)
            logger.info(f"Sync devis depuis: {depuis_date or 'début'} (sleep {sleep_sec}s/itération)")

            devis_list = await self.get_devis_acceptes(depuis_date)
            total_a_traiter = len(devis_list)
            logger.info(f"Devis trouvés: {total_a_traiter}")

            async with httpx.AsyncClient(timeout=30.0) as http_client:
                for index, devis_data in enumerate(devis_list, start=1):
                    # Sleep en tête d'itération : protège tous les appels Karlia
                    # de cette itération (detail, customer, opportunité, marquage)
                    # contre le quota 100 req/min.
                    await asyncio.sleep(sleep_sec)

                    commande_traitee: Optional[Commande] = None
                    try:
                        karlia_id = devis_data.get("id")
                        if not karlia_id:
                            continue

                        # Défense en profondeur : rejet d'un document de mauvais type.
                        # Karlia v2 filtre déjà côté serveur via `type=1`, mais ce
                        # filtre Python protège contre une régression future (changement
                        # de comportement API, nouveau type introduit, etc.).
                        id_type_recu = int(devis_data.get("id_type", 0))
                        if id_type_recu != KARLIA_TYPE_DEVIS:
                            logger.warning(
                                f"Document Karlia rejeté (id_type={id_type_recu}, "
                                f"number={devis_data.get('number')}, "
                                f"karlia_document_id={karlia_id}) — attendu id_type=1"
                            )
                            result["documents_rejetes_par_type"] += 1
                            continue

                        id_opportunity = devis_data.get("id_opportunity")
                        has_opp = bool(id_opportunity and id_opportunity != "0")

                        # ── Vérifier si l'opportunité est déjà traitée ──
                        opp_traitee = False
                        if has_opp:
                            await asyncio.sleep(0.5)
                            opp_traitee = await self._is_opportunity_traitee(http_client, id_opportunity)

                        existing = db.query(Commande).filter(
                            Commande.karlia_document_id == int(karlia_id)
                        ).first()

                        if opp_traitee and not existing:
                            # Opportunité déjà traitée côté Karlia et aucune commande
                            # locale : on ignore ce devis (gardien contre la réimport).
                            result["devis_ignores"] += 1
                            logger.info(f"Devis {karlia_id} ignoré: opportunité {id_opportunity} déjà traitée")
                        elif existing:
                            # Commande déjà en base (opportunité traitée ou non) → MAJ
                            commande_traitee = await self._update_commande(db, existing, devis_data)
                            result["devis_mis_a_jour"] += 1
                        else:
                            # Nouveau devis (opportunité non traitée ou absente)
                            commande_traitee = await self._create_commande(db, devis_data)

                            # Stocker l'id opportunité + marquer Karlia
                            if has_opp:
                                from sqlalchemy import text
                                db.execute(
                                    text("UPDATE commandes SET karlia_opportunity_id = :opp_id WHERE id = :id"),
                                    {"opp_id": int(id_opportunity), "id": commande_traitee.id}
                                )
                                db.commit()

                                await asyncio.sleep(0.8)
                                if await self._marquer_opportunity_traitee(http_client, id_opportunity):
                                    result["opportunites_marquees"] += 1

                            result["nouveaux_devis"] += 1

                    except Exception as e:
                        error_msg = f"Erreur devis {devis_data.get('id', '?')}: {str(e)}"
                        logger.error(error_msg)
                        result["erreurs"].append(error_msg)

                    # Comptabilité PDF : sur toute commande créée ou mise à jour
                    if commande_traitee is not None:
                        if commande_traitee.pdf_url:
                            result["pdf_url_renseigne"] += 1
                        else:
                            result["pdf_url_absent"] += 1
                            logger.warning(
                                f"Commande sans pdf_url après sync — "
                                f"karlia_document_id={commande_traitee.karlia_document_id} "
                                f"ref={commande_traitee.reference_devis} id={commande_traitee.id} "
                                f"(échec détail Karlia : 429 persistant ou 404)"
                            )

                    # Progression toutes les 20 commandes
                    if index % 20 == 0:
                        logger.info(
                            f"Sync progression: {index}/{total_a_traiter} traités "
                            f"(nouveaux={result['nouveaux_devis']}, "
                            f"maj={result['devis_mis_a_jour']}, "
                            f"ignorés={result['devis_ignores']}, "
                            f"pdf_url ok={result['pdf_url_renseigne']} "
                            f"absent={result['pdf_url_absent']})"
                        )

            self._set_derniere_synchro(db, datetime.utcnow())
            result["message"] = (
                f"Sync terminée: {result['nouveaux_devis']} nouveaux, "
                f"{result['devis_mis_a_jour']} MAJ, "
                f"{result['devis_ignores']} ignorés (déjà traités), "
                f"{result['documents_rejetes_par_type']} rejetés (mauvais type), "
                f"{result['opportunites_marquees']} opportunités marquées | "
                f"PDF: {result['pdf_url_renseigne']} ok, {result['pdf_url_absent']} absent"
            )
            logger.info(result["message"])
        except Exception as e:
            result["success"] = False
            result["message"] = f"Erreur sync: {str(e)}"
            result["erreurs"].append(str(e))
            logger.error(f"Erreur sync: {e}")

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Création / mise à jour de commande
    # ─────────────────────────────────────────────────────────────────────────

    async def _create_commande(self, db: Session, devis_data: Dict[str, Any]) -> Commande:
        """Crée une commande à partir d'un devis Karlia."""
        # Récupérer le détail complet du devis
        devis_detail = await self.get_devis_detail(devis_data["id"])
        if devis_detail:
            devis_data.update(devis_detail)

        customer_id = devis_data.get("id_customer_supplier") or devis_data.get("id_customer")
        client_info = {}
        if customer_id:
            customer_data = await self.get_customer_detail(customer_id)
            if customer_data:
                adresse = ""
                address_list = customer_data.get("address_list", [])
                if address_list:
                    main_addr = address_list[0]
                    adresse_parts = []
                    if main_addr.get("address"):
                        adresse_parts.append(main_addr["address"])
                    if main_addr.get("zip_code") or main_addr.get("city"):
                        adresse_parts.append(f"{main_addr.get('zip_code', '')} {main_addr.get('city', '')}".strip())
                    adresse = "\n".join(adresse_parts)

                client_info = {
                    "client_nom": customer_data.get("title") or customer_data.get("name"),
                    "client_email": customer_data.get("email"),
                    "client_telephone": customer_data.get("phone"),
                    "client_adresse": adresse,
                    "client_siret": customer_data.get("siret")
                }

        commande = Commande(
            karlia_document_id=int(devis_data["id"]),
            karlia_customer_id=int(customer_id) if customer_id else None,
            reference_devis=devis_data.get("number"),
            client_nom=client_info.get("client_nom") or devis_data.get("customer_supplier_title"),
            client_email=client_info.get("client_email"),
            client_telephone=client_info.get("client_telephone"),
            client_adresse=client_info.get("client_adresse"),
            client_siret=client_info.get("client_siret"),
            montant_ht=devis_data.get("total_without_tax"),
            montant_tva=float(devis_data.get("total_with_tax", 0)) - float(devis_data.get("total_without_tax", 0)),
            montant_ttc=devis_data.get("total_with_tax"),
            date_devis=self._parse_karlia_date(devis_data.get("date")),
            date_acceptation=self._parse_karlia_date(devis_data.get("update_date", "").split(" ")[0] if devis_data.get("update_date") else None),
            statut="nouvelle",
            pdf_url=devis_data.get("download_url"),
            pdf_devis_nom=f"{devis_data.get('number', 'devis')}.pdf"
        )

        db.add(commande)
        db.flush()

        # Ajouter les lignes de produits
        products = devis_data.get("products_list") or []
        for idx, product in enumerate(products):
            ligne = CommandeLigne(
                commande_id=commande.id,
                karlia_product_id=str(product.get("id_product") or ""),
                designation=product.get("title") or product.get("description"),
                description=product.get("description"),
                quantite=product.get("quantity", 1),
                unite=product.get("unit"),
                prix_unitaire_ht=product.get("price_without_tax"),
                taux_tva=self._parse_tva(product.get("id_vat")) or float(product.get("vat", 0)),
                montant_ht=product.get("total_without_tax"),
                ordre=idx
            )
            db.add(ligne)

        db.commit()
        logger.info(f"Commande créée: {commande.reference_devis}")
        return commande

    async def _update_commande(self, db: Session, commande: Commande, devis_data: Dict[str, Any]) -> Commande:
        """Met à jour une commande existante avec les données fraîches du devis."""
        devis_detail = await self.get_devis_detail(devis_data["id"])
        if devis_detail:
            devis_data.update(devis_detail)

        commande.montant_ht = devis_data.get("total_without_tax") or commande.montant_ht
        commande.montant_ttc = devis_data.get("total_with_tax") or commande.montant_ttc
        commande.montant_tva = float(commande.montant_ttc or 0) - float(commande.montant_ht or 0)
        commande.updated_at = datetime.utcnow()

        # Mettre à jour l'URL PDF si disponible
        if devis_data.get("download_url"):
            commande.pdf_url = devis_data.get("download_url")
            commande.pdf_devis_nom = f"{devis_data.get('number', 'devis')}.pdf"

        db.commit()
        return commande


karlia_devis_service = KarliaDevisService()
