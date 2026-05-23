"""
Service de synchronisation des BONS DE COMMANDE acceptés depuis Karlia.

Historiquement, ce module rapatriait les DEVIS Karlia (type=1, statut accepté).
Depuis la refonte v3.1, la source est désormais les BONS DE COMMANDE Karlia
(type=2, statut validé). Les noms de méthodes publiques (sync_devis_acceptes,
get_devis_detail, get_customer_detail, _create_commande, _update_commande) sont
CONSERVÉS pour ne pas casser l'API REST (commandes.py) ; seul le comportement
change.

Chaîne de résolution d'un BC :
- Le BC ne porte pas le client (id_customer / id_customer_supplier = null).
- BC.id_opportunity → GET /opportunities/{id} → id_customer_supplier =
  karlia_id du client (clé de liaison Karlia ↔ SGI, distincte du numero_client
  côté SGI).

Garde-fou anti-réimport :
- On NE s'appuie PLUS sur le champ custom "Traité" (Karlia) pour décider
  d'ignorer un BC.
- À la place : si une commande au statut AVANCÉ (a_planifier, planifiee,
  deployee, facturee, terminee) existe déjà en base pour la même
  karlia_opportunity_id → on SKIP le BC (l'affaire est déjà prise en charge).
- Une commande au statut 'nouvelle' pour la même opportunité est, elle, mise
  à jour à la volée (cas marginal après la purge initiale, conservé par
  robustesse en cas d'import partiel).
- Le marquage "Traité" Karlia est CONSERVÉ après création réussie d'un BC
  (POST custom-fields/66505), mais ne sert plus de critère de décision.

Rate-limiting Karlia (quota 100 req/min) :
- Sleep configurable (settings.KARLIA_SYNC_SLEEP_SECONDS, défaut 1.2s) en tête
  de chaque itération du loop de sync (≈ 4 appels par BC (detail + opportunité
  + customer + marquage Traité), customer mémoïsé).
- Retry automatique sur 429 (backoff 5s → 15s → 30s) dans `_get_with_retry`.
- Les erreurs HTTP autres que 429 (404, 5xx…) ne déclenchent pas de retry :
  elles sont loguées et la méthode renvoie None.

Mémoïsation intra-passe : deux dicts (opp_cache, client_cache_mem) évitent
les appels répétés pour les BC partageant la même opportunité/le même client.
"""
import httpx
import asyncio
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import Commande, CommandeLigne, Parametre, ClientCache

logger = logging.getLogger(__name__)

KARLIA_TYPE_DEVIS = 1
KARLIA_TYPE_BON_COMMANDE = 2
KARLIA_STATUS_BC_VALIDE = 2
KARLIA_FIELD_TRAITE_ID = "66505"

# Statuts considérés comme "avancés" : un BC dont l'opportunité a déjà
# une commande dans l'un de ces statuts est ignoré (l'affaire est prise
# en charge ou clôturée côté SGI).
STATUTS_AVANCES = ("a_planifier", "planifiee", "deployee", "facturee", "terminee")

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
    # API Karlia — Documents (bons de commande)
    # ─────────────────────────────────────────────────────────────────────────

    async def get_devis_acceptes(self, depuis_date: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """
        Récupère tous les BONS DE COMMANDE validés depuis Karlia, paginés.

        Filtre côté serveur : type=2 (BC) + id_status=2 (validé).
        Filtre côté Python : on RE-VÉRIFIE str(id_status)=="2" car les listings
        Karlia renvoient id_status en STRING et ont par le passé inclus des
        brouillons (id_status=1) ou des statuts hors-périmètre (0).
        """
        bons_commande = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            offset = 0
            limit = 100
            while True:
                params = {
                    # NB: Karlia v2 attend `type` (pas `id_type` qui est silencieusement
                    # ignoré). Validé par test live le 2026-05-20 — voir commit message
                    # et fix/cleanup-bc-commandes pour le contexte.
                    "type": KARLIA_TYPE_BON_COMMANDE,
                    "id_status": KARLIA_STATUS_BC_VALIDE,
                    "limit": limit,
                    "offset": offset,
                }
                if depuis_date:
                    params["update_date_min"] = depuis_date.strftime("%Y-%m-%d")

                response = await self._get_with_retry(
                    client,
                    f"{self.base_url}/documents",
                    params=params,
                    context=f"listing BC offset={offset}",
                )
                if response is None:
                    break
                data = response.json()
                documents = data.get("data", [])
                # Filtre Python (id_status renvoyé en STRING par Karlia).
                bons_filtres = [d for d in documents if str(d.get("id_status")) == "2"]
                bons_commande.extend(bons_filtres)
                total = data.get("pagination", {}).get("total", 0)
                if len(bons_commande) >= total or len(documents) < limit:
                    break
                offset += limit
                await asyncio.sleep(0.8)

        return bons_commande

    async def get_devis_detail(self, document_id: int) -> Optional[Dict[str, Any]]:
        """Récupère le détail complet d'un BC (produits, PDF, etc.)."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await self._get_with_retry(
                client,
                f"{self.base_url}/documents/{document_id}",
                context=f"detail BC {document_id}",
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

    async def get_opportunity_detail(self, opportunity_id) -> Optional[Dict[str, Any]]:
        """Récupère les infos d'une opportunité Karlia."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await self._get_with_retry(
                client,
                f"{self.base_url}/opportunities/{opportunity_id}",
                context=f"opportunite {opportunity_id}",
            )
            if response is None:
                return None
            data = response.json()
            # L'API Karlia enveloppe parfois la ressource dans {data: {...}}
            return data.get("data") if isinstance(data, dict) and "data" in data else data

    # ─────────────────────────────────────────────────────────────────────────
    # API Karlia — Opportunités (marquage "Traité")
    # ─────────────────────────────────────────────────────────────────────────

    async def _is_opportunity_traitee(self, client: httpx.AsyncClient, opportunity_id: str) -> bool:
        """
        Vérifie si une opportunité est déjà marquée 'Traité' dans Karlia.

        DEPRECATED depuis v3.1 : conservée pour compatibilité descendante mais
        plus appelée dans le flux de sync — le skip est désormais basé sur le
        statut local de la commande (cf. STATUTS_AVANCES).
        """
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
        Synchronise les BONS DE COMMANDE validés depuis Karlia.

        Flux par BC :
          1. Filtrage type=2 + id_status=2 (serveur ET Python).
          2. Résolution opportunité (mémoïsée) → id_customer_supplier.
             Si pas d'opportunité : rejet (un BC sans opportunité ne peut pas
             résoudre son client).
          3. Garde-fou : si une commande existe déjà pour cette opportunité
             dans un statut AVANCÉ → SKIP (l'affaire est déjà prise en charge).
          4. Sinon : MAJ si une commande 'nouvelle' existe pour cette
             opportunité (cas marginal après la purge), sinon CREATE.
          5. Après CREATE/UPDATE confirmée : marquage "Traité" Karlia
             (custom-fields/66505).

        - Sleep settings.KARLIA_SYNC_SLEEP_SECONDS entre chaque itération pour
          rester sous le quota Karlia 100 req/min (≈ 4 appels par BC (detail +
          opportunité + customer + marquage Traité), customer mémoïsé).
        """
        result = {
            "success": True,
            "nouveaux_devis": 0,            # BC créés
            "devis_mis_a_jour": 0,          # BC mis à jour (cas 'nouvelle' existante)
            "devis_ignores": 0,             # BC sans opportunité ou opportunité non résolue
            "ignores_avances": 0,           # BC dont l'affaire est déjà en statut avancé
            "documents_rejetes_par_type": 0,
            "opportunites_marquees": 0,
            "pdf_url_renseigne": 0,
            "pdf_url_absent": 0,
            "erreurs": [],
            "message": ""
        }

        sleep_sec = settings.KARLIA_SYNC_SLEEP_SECONDS

        # Mémoïsation intra-passe : évite les appels répétés pour les BC
        # partageant la même opportunité ou le même client.
        opp_cache: Dict[Any, Optional[Dict[str, Any]]] = {}
        client_cache_mem: Dict[Any, Optional[Dict[str, Any]]] = {}

        try:
            depuis_date = None if force_full else self._get_derniere_synchro(db)
            logger.info(f"Sync BC depuis: {depuis_date or 'début'} (sleep {sleep_sec}s/itération)")

            bc_list = await self.get_devis_acceptes(depuis_date)
            total_a_traiter = len(bc_list)
            logger.info(f"Bons de commande trouvés: {total_a_traiter}")

            async with httpx.AsyncClient(timeout=30.0) as http_client:
                for index, bc_data in enumerate(bc_list, start=1):
                    # Sleep en tête d'itération : protège tous les appels Karlia
                    # de cette itération contre le quota 100 req/min.
                    await asyncio.sleep(sleep_sec)

                    commande_traitee: Optional[Commande] = None
                    try:
                        karlia_id = bc_data.get("id")
                        if not karlia_id:
                            continue

                        # Défense en profondeur : rejet d'un document de mauvais type.
                        # Karlia v2 filtre déjà côté serveur via `type=2`, mais ce
                        # filtre Python protège contre une régression future.
                        id_type_recu = int(bc_data.get("id_type", 0))
                        if id_type_recu != KARLIA_TYPE_BON_COMMANDE:
                            logger.warning(
                                f"Document Karlia rejeté (id_type={id_type_recu}, "
                                f"number={bc_data.get('number')}, "
                                f"karlia_document_id={karlia_id}) — attendu id_type=2"
                            )
                            result["documents_rejetes_par_type"] += 1
                            continue

                        id_opportunity = bc_data.get("id_opportunity")
                        if not id_opportunity or str(id_opportunity) == "0":
                            logger.warning(
                                f"BC {bc_data.get('number')} (id={karlia_id}) ignoré : "
                                f"aucune id_opportunity — client non résolvable."
                            )
                            result["devis_ignores"] += 1
                            continue

                        # ── Résolution opportunité (mémoïsée) ──
                        if id_opportunity in opp_cache:
                            opp_data = opp_cache[id_opportunity]
                        else:
                            opp_data = await self.get_opportunity_detail(id_opportunity)
                            opp_cache[id_opportunity] = opp_data

                        if not opp_data:
                            logger.warning(
                                f"BC {bc_data.get('number')} ignoré : opportunité "
                                f"{id_opportunity} introuvable côté Karlia."
                            )
                            result["devis_ignores"] += 1
                            continue

                        id_customer_supplier = opp_data.get("id_customer_supplier")
                        if not id_customer_supplier:
                            logger.warning(
                                f"BC {bc_data.get('number')} ignoré : opportunité "
                                f"{id_opportunity} sans id_customer_supplier."
                            )
                            result["devis_ignores"] += 1
                            continue

                        # Injection du client résolu dans bc_data pour que
                        # _create_commande / _update_commande fonctionnent
                        # inchangés (ils lisent id_customer_supplier).
                        bc_data["id_customer_supplier"] = id_customer_supplier

                        # ── Garde-fou anti-réimport : statut avancé déjà présent ──
                        opp_id_int = int(id_opportunity)
                        commande_avancee = db.query(Commande).filter(
                            Commande.karlia_opportunity_id == opp_id_int,
                            Commande.statut.in_(STATUTS_AVANCES),
                        ).first()
                        if commande_avancee:
                            logger.info(
                                f"BC {bc_data.get('number')} ignoré : commande "
                                f"{commande_avancee.reference_devis} (id={commande_avancee.id}) "
                                f"déjà au statut '{commande_avancee.statut}' "
                                f"pour opportunité {id_opportunity}."
                            )
                            result["ignores_avances"] += 1
                            continue

                        # ── MAJ d'une commande 'nouvelle' existante ──
                        existing_nouvelle = db.query(Commande).filter(
                            Commande.karlia_opportunity_id == opp_id_int,
                            Commande.statut == "nouvelle",
                        ).first()

                        if existing_nouvelle:
                            commande_traitee = await self._update_commande(
                                db, existing_nouvelle, bc_data,
                                client_cache_mem=client_cache_mem,
                            )
                            result["devis_mis_a_jour"] += 1
                        else:
                            # ── Création ──
                            commande_traitee = await self._create_commande(
                                db, bc_data,
                                client_cache_mem=client_cache_mem,
                                opportunity_id=opp_id_int,
                            )
                            result["nouveaux_devis"] += 1

                        # ── Marquage "Traité" Karlia après succès ──
                        if commande_traitee is not None:
                            await asyncio.sleep(0.8)
                            if await self._marquer_opportunity_traitee(http_client, id_opportunity):
                                result["opportunites_marquees"] += 1

                    except Exception as e:
                        error_msg = f"Erreur BC {bc_data.get('id', '?')}: {str(e)}"
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

                    # Progression toutes les 20 BC
                    if index % 20 == 0:
                        logger.info(
                            f"Sync progression: {index}/{total_a_traiter} traités "
                            f"(nouveaux={result['nouveaux_devis']}, "
                            f"maj={result['devis_mis_a_jour']}, "
                            f"ignorés={result['devis_ignores']}, "
                            f"ignorés_avancés={result['ignores_avances']}, "
                            f"pdf_url ok={result['pdf_url_renseigne']} "
                            f"absent={result['pdf_url_absent']})"
                        )

            self._set_derniere_synchro(db, datetime.utcnow())
            result["message"] = (
                f"Sync BC terminée: {result['nouveaux_devis']} nouveaux, "
                f"{result['devis_mis_a_jour']} MAJ, "
                f"{result['devis_ignores']} ignorés (sans client résolvable), "
                f"{result['ignores_avances']} ignorés (statut avancé déjà existant), "
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

    async def _fetch_customer_memo(
        self,
        customer_id,
        client_cache_mem: Optional[Dict[Any, Optional[Dict[str, Any]]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Récupère le client Karlia avec mémoïsation intra-passe."""
        if not customer_id:
            return None
        if client_cache_mem is not None and customer_id in client_cache_mem:
            return client_cache_mem[customer_id]
        customer_data = await self.get_customer_detail(customer_id)
        if client_cache_mem is not None:
            client_cache_mem[customer_id] = customer_data
        return customer_data

    def _upsert_client_cache(self, db: Session, customer_id, customer_data: Dict[str, Any]) -> None:
        """
        Crée l'entrée ClientCache si absente (clé : karlia_id = customer_id).
        Le numero_client SGI est laissé tel quel s'il existe déjà (on NE
        touche PAS à la convention de numérotation côté SGI).
        """
        if not customer_id or not customer_data:
            return
        karlia_id_str = str(customer_id)
        existing = db.query(ClientCache).filter(ClientCache.karlia_id == karlia_id_str).first()
        if existing is not None:
            return  # déjà en cache — pas de besoin de réécrire les champs SGI

        numero_client = customer_data.get("client_number") or karlia_id_str
        nom = customer_data.get("title") or customer_data.get("name") or f"Client {karlia_id_str}"
        adresse_ligne1 = None
        code_postal = None
        ville = None
        address_list = customer_data.get("address_list") or []
        if address_list:
            main_addr = address_list[0]
            adresse_ligne1 = main_addr.get("address")
            code_postal = main_addr.get("zip_code")
            ville = main_addr.get("city")

        cache = ClientCache(
            karlia_id=karlia_id_str,
            numero_client=str(numero_client),
            nom=nom,
            adresse_ligne1=adresse_ligne1,
            code_postal=code_postal,
            ville=ville,
            email=customer_data.get("email"),
            telephone=customer_data.get("phone"),
            mobile=customer_data.get("mobile"),
            siret=customer_data.get("siret"),
            tva_intracom=customer_data.get("vat_number"),
            synchro_at=datetime.utcnow(),
        )
        db.add(cache)
        try:
            db.flush()
        except Exception as e:
            logger.warning(f"ClientCache upsert ignoré pour karlia_id={karlia_id_str}: {e}")
            db.rollback()

    async def _create_commande(
        self,
        db: Session,
        devis_data: Dict[str, Any],
        client_cache_mem: Optional[Dict[Any, Optional[Dict[str, Any]]]] = None,
        opportunity_id: Optional[int] = None,
    ) -> Commande:
        """Crée une commande à partir d'un BC Karlia."""
        # Récupérer le détail complet du BC (produits, PDF)
        bc_detail = await self.get_devis_detail(devis_data["id"])
        if bc_detail:
            # Préserver l'id_customer_supplier injecté en amont (le detail
            # peut ne pas le contenir)
            preserved_customer = devis_data.get("id_customer_supplier")
            devis_data.update(bc_detail)
            if preserved_customer and not devis_data.get("id_customer_supplier"):
                devis_data["id_customer_supplier"] = preserved_customer

        customer_id = devis_data.get("id_customer_supplier") or devis_data.get("id_customer")
        client_info = {}
        customer_data: Optional[Dict[str, Any]] = None
        if customer_id:
            customer_data = await self._fetch_customer_memo(customer_id, client_cache_mem)
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

                # Alimentation du ClientCache si absent
                self._upsert_client_cache(db, customer_id, customer_data)

        commande = Commande(
            karlia_document_id=int(devis_data["id"]),
            karlia_customer_id=int(customer_id) if customer_id else None,
            karlia_opportunity_id=opportunity_id,
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
            pdf_devis_nom=f"{devis_data.get('number', 'bc')}.pdf"
        )

        db.add(commande)
        db.flush()

        # Ajouter les lignes de produits (même structure que les devis)
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
        logger.info(f"Commande créée (BC): {commande.reference_devis}")
        return commande

    async def _update_commande(
        self,
        db: Session,
        commande: Commande,
        devis_data: Dict[str, Any],
        client_cache_mem: Optional[Dict[Any, Optional[Dict[str, Any]]]] = None,
    ) -> Commande:
        """
        Met à jour une commande 'nouvelle' existante avec les données fraîches
        d'un nouveau BC pour la même opportunité. Régénère les lignes depuis
        le BC.
        """
        bc_detail = await self.get_devis_detail(devis_data["id"])
        if bc_detail:
            preserved_customer = devis_data.get("id_customer_supplier")
            devis_data.update(bc_detail)
            if preserved_customer and not devis_data.get("id_customer_supplier"):
                devis_data["id_customer_supplier"] = preserved_customer

        # Le document Karlia peut être un BC différent du précédent pour la
        # même opportunité (révision, nouveau BC) → on remplace la référence.
        commande.karlia_document_id = int(devis_data["id"])
        commande.reference_devis = devis_data.get("number") or commande.reference_devis

        customer_id = devis_data.get("id_customer_supplier") or devis_data.get("id_customer")
        if customer_id:
            customer_data = await self._fetch_customer_memo(customer_id, client_cache_mem)
            if customer_data:
                commande.karlia_customer_id = int(customer_id)
                commande.client_nom = customer_data.get("title") or customer_data.get("name") or commande.client_nom
                commande.client_email = customer_data.get("email") or commande.client_email
                commande.client_telephone = customer_data.get("phone") or commande.client_telephone
                commande.client_siret = customer_data.get("siret") or commande.client_siret
                address_list = customer_data.get("address_list", []) or []
                if address_list:
                    main_addr = address_list[0]
                    adresse_parts = []
                    if main_addr.get("address"):
                        adresse_parts.append(main_addr["address"])
                    if main_addr.get("zip_code") or main_addr.get("city"):
                        adresse_parts.append(f"{main_addr.get('zip_code', '')} {main_addr.get('city', '')}".strip())
                    commande.client_adresse = "\n".join(adresse_parts) or commande.client_adresse
                self._upsert_client_cache(db, customer_id, customer_data)

        commande.montant_ht = devis_data.get("total_without_tax") or commande.montant_ht
        commande.montant_ttc = devis_data.get("total_with_tax") or commande.montant_ttc
        commande.montant_tva = float(commande.montant_ttc or 0) - float(commande.montant_ht or 0)
        commande.date_devis = self._parse_karlia_date(devis_data.get("date")) or commande.date_devis
        if devis_data.get("update_date"):
            commande.date_acceptation = self._parse_karlia_date(
                devis_data["update_date"].split(" ")[0]
            ) or commande.date_acceptation
        commande.updated_at = datetime.utcnow()

        # Mettre à jour l'URL PDF si disponible
        if devis_data.get("download_url"):
            commande.pdf_url = devis_data.get("download_url")
            commande.pdf_devis_nom = f"{devis_data.get('number', 'bc')}.pdf"

        # Régénérer les lignes depuis le BC (cas marginal : MAJ d'une commande
        # 'nouvelle' jamais validée → on accepte la perte des anciennes lignes
        # car elles n'ont pas encore été consommées par une prestation).
        products = devis_data.get("products_list")
        if products is not None:
            for ligne in list(commande.lignes):
                db.delete(ligne)
            db.flush()
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
        logger.info(f"Commande mise à jour (BC): {commande.reference_devis}")
        return commande


karlia_devis_service = KarliaDevisService()
