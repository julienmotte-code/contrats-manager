"""
Service de construction des FACTURES FOURNISSEURS côté SGI à partir des
BONS DE RÉCEPTION Karlia (suppliers-documents, id_type=3).

Périmètre de ce service :
- Lecture seule côté Karlia (pagination /products + /suppliers-documents).
- CRUD complet du brouillon côté SGI (factures_fournisseurs,
  factures_fournisseurs_lignes, factures_fournisseurs_pointage).
- Anti-doublon avec cumul partiel : à la VALIDATION uniquement, on incrémente
  quantite_facturee_cumulee sur (id_bl_karlia, ligne_index).

Pas d'émission Karlia : POST /suppliers-documents renvoie "API not available"
côté Karlia (en attente support). Les colonnes id_suppliers_document_karlia
et statut_emission_karlia restent NULL — l'émission sera branchée plus tard
sans refonte.

Pièges Karlia respectés ici :
- HTTP 200 ne signifie PAS succès : on inspecte systématiquement le CORPS
  (présence de "data", clé "status" en erreur, message "API not available").
- Le filtre serveur (ex. ?id_type=3) n'est pas fiable : on re-filtre côté
  Python après réception.
- Rate-limit ~100 req/min : délai 0.8 s ENTRE deux appels Karlia (jamais
  après le dernier — c'est inutile et ça allonge la durée perçue).
- Clé API : héritée de la singleton `karlia` (KarliaService), rechargée
  depuis la table parametres au startup de FastAPI.

Optimisations en place :
- Catalogue produits (~400 entrées, 4 pages) : cache mémoire module-level
  avec TTL configurable (settings.KARLIA_CATALOGUE_CACHE_TTL). `force_refresh`
  permet de bypasser le cache (bouton "Rafraîchir" côté UI).
- creer_brouillon / mettre_a_jour_brouillon : UN seul GET /suppliers-documents/{id}
  par BR distinct, dont le résultat sert à la fois à la vérif fournisseur
  ET au recontrôle des quantités (cf. livraisons_precharge).
- factures_fournisseurs_lignes.quantite_max_facturable : snapshot du
  restant à la création — évite au front de rappeler /facturables pour
  borner les champs `max` de l'édition.
"""
from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.models.models import (
    ClientCache,
    FactureFournisseur,
    FactureFournisseurLigne,
    FactureFournisseurPointage,
)
from app.services.karlia_service import karlia, KarliaError

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Constantes Karlia
# ─────────────────────────────────────────────────────────────────────────────

# Catégories de produits à exclure du flux factures fournisseurs.
# 19028 : PRESTATIONS : SGI - Technique
# 16374 : PRESTATIONS : SGI - FORMATION
CATEGORIES_EXCLUES = {19028, 16374}

# Types de documents fournisseurs Karlia (mêmes valeurs que /documents).
KARLIA_SUPPLIER_TYPE_BON_RECEPTION = 3
KARLIA_SUPPLIER_TYPE_FACTURE = 4

# Pagination
PAGE_SIZE = 100
DELAI_ENTRE_APPELS = 0.8  # secondes — sous le quota 100 req/min

# Mapping TVA Karlia → taux %. Identique à
# `karlia_devis_service._parse_tva`. Redéfini ici en constante par
# souci de lisibilité (le service factures fournisseurs n'a pas
# besoin d'importer karlia_devis_service pour ça).
TVA_TAUX_PAR_ID_VAT: Dict[str, Decimal] = {
    "1": Decimal("20.0"),
    "2": Decimal("10.0"),
    "3": Decimal("5.5"),
    "4": Decimal("0.0"),
}


# ─────────────────────────────────────────────────────────────────────────────
# Cache mémoire du catalogue produits (module-level, async-safe)
# ─────────────────────────────────────────────────────────────────────────────
#
# Le mapping id_product -> id_product_category coûte ~4 s à charger
# (4 pages /products + 3 sleeps de 0.8 s). Comme il change rarement
# (création/déplacement de produits dans Karlia), on le cache en mémoire
# avec un TTL configurable (settings.KARLIA_CATALOGUE_CACHE_TTL).
#
# Le cache est partagé entre toutes les requêtes du process backend
# (variables module-level). Le verrou asyncio évite qu'un cache miss
# concurrent provoque deux chargements parallèles.
#
# Forcer le rafraîchissement : appeler avec force_refresh=True (utilisé
# par le bouton "Rafraîchir" côté UI).

_CATALOGUE_CACHE_MAPPING: Optional[Dict[int, int]] = None
_CATALOGUE_CACHE_TIMESTAMP: float = 0.0
_CATALOGUE_CACHE_LOCK: Optional[asyncio.Lock] = None


def _get_catalogue_lock() -> asyncio.Lock:
    """Crée le verrou asyncio paresseusement (asyncio.Lock doit être
    instancié dans une event loop, ce qui n'est pas garanti au moment
    de l'import du module)."""
    global _CATALOGUE_CACHE_LOCK
    if _CATALOGUE_CACHE_LOCK is None:
        _CATALOGUE_CACHE_LOCK = asyncio.Lock()
    return _CATALOGUE_CACHE_LOCK


class KarliaBodyError(Exception):
    """Levée quand Karlia renvoie HTTP 200 avec un corps en erreur
    (ex. {"status": "error", "message": "API not available"}) ou un corps
    qui n'a pas la forme attendue (pas de clé "data" sur un listing).

    Cette exception est traduite en HTTP 502 par le routeur.
    """

    def __init__(self, endpoint: str, message: str, body: Optional[dict] = None):
        self.endpoint = endpoint
        self.message = message
        self.body = body or {}
        super().__init__(f"Karlia ({endpoint}) : {message}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internes
# ─────────────────────────────────────────────────────────────────────────────


def _check_karlia_body(endpoint: str, body: Any, *, expect_data_list: bool) -> dict:
    """Vérifie qu'un corps de réponse Karlia est exploitable.

    Karlia v2 renvoie HTTP 200 même sur erreur ; le détail est dans le corps.
    Levée d'une `KarliaBodyError` si :
      - body n'est pas un dict
      - body["status"] == "error" (ou champ "message" type "API not available")
      - expect_data_list=True et "data" absent ou non-liste
    """
    if not isinstance(body, dict):
        raise KarliaBodyError(
            endpoint,
            f"corps non-dict (type {type(body).__name__})",
            {"raw": body if isinstance(body, (str, list)) else None},
        )

    status_value = body.get("status")
    message_value = body.get("message")
    # Karlia signale parfois l'erreur dans "status" (string) ou "message".
    if isinstance(status_value, str) and status_value.lower() in {"error", "ko", "ko."}:
        raise KarliaBodyError(
            endpoint,
            f"statut d'erreur Karlia : {message_value or status_value}",
            body,
        )
    if isinstance(message_value, str) and "not available" in message_value.lower():
        raise KarliaBodyError(endpoint, message_value, body)
    if isinstance(message_value, str) and "not found" in message_value.lower():
        raise KarliaBodyError(endpoint, message_value, body)

    if expect_data_list:
        data = body.get("data")
        if not isinstance(data, list):
            raise KarliaBodyError(
                endpoint,
                "champ 'data' absent ou non-liste sur un listing",
                body,
            )

    return body


def _to_int_or_none(value: Any) -> Optional[int]:
    """Convertit en int en tolérant les strings, None, '0' Karlia, etc."""
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    """Conversion robuste en Decimal (gère int, float, string, None)."""
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _taux_tva_pour_id_vat(id_vat: Optional[str]) -> Decimal:
    """Retourne le taux % associé à un id_vat Karlia. Défaut 20 % si inconnu."""
    if id_vat is None:
        return Decimal("20.0")
    key = str(id_vat).strip()
    return TVA_TAUX_PAR_ID_VAT.get(key, Decimal("20.0"))


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class KarliaFacturesFournisseursService:
    """Service côté SGI pour les factures fournisseurs construites depuis
    les bons de réception Karlia.

    Réutilise la singleton `karlia` (KarliaService) pour les appels HTTP
    (auth, base URL, gestion 401/429), et y ajoute :
    - l'inspection du CORPS (HTTP 200 ne signifie pas succès chez Karlia),
    - le re-filtrage côté Python (le filtre serveur ?id_type=3 n'est pas fiable).
    """

    # ── Karlia : catalogue produits & catégories ──────────────────────────

    async def _charger_mapping_categories_reseau(self) -> Dict[int, int]:
        """Charge le mapping { id_product : id_product_category } depuis
        Karlia (GET /products paginé). Sleep ENTRE deux pages, jamais
        après la dernière.
        """
        mapping: Dict[int, int] = {}
        offset = 0
        endpoint = "/products"

        while True:
            params = {"limit": PAGE_SIZE, "offset": offset}
            try:
                body = await karlia._get(endpoint, params)
            except KarliaError as e:
                # 401 / 429 / 5xx — on remonte tel quel après log structuré.
                logger.error(
                    "karlia_factures_fournisseurs.products: erreur HTTP",
                    extra={
                        "endpoint": endpoint,
                        "offset": offset,
                        "status_code": e.status_code,
                        "message": e.message,
                    },
                )
                raise

            _check_karlia_body(endpoint, body, expect_data_list=True)
            data = body["data"]

            for produit in data:
                pid = _to_int_or_none(produit.get("id"))
                cat = _to_int_or_none(produit.get("id_product_category"))
                if pid is not None and cat is not None:
                    mapping[pid] = cat

            logger.info(
                "karlia_factures_fournisseurs.products: page chargée",
                extra={
                    "endpoint": endpoint,
                    "offset": offset,
                    "page_size": len(data),
                    "mapping_total": len(mapping),
                },
            )

            if len(data) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            await asyncio.sleep(DELAI_ENTRE_APPELS)

        return mapping

    async def charger_mapping_categories(
        self, *, force_refresh: bool = False
    ) -> Tuple[Dict[int, int], bool]:
        """Retourne (mapping, cache_hit).

        cache_hit=True signifie que le mapping vient du cache mémoire (aucun
        appel Karlia n'a été fait) ; l'appelant peut s'en servir pour éviter
        un sleep d'inter-phase inutile.

        Verrou asyncio : si deux requêtes arrivent en cache miss au même
        moment, une seule charge le catalogue (l'autre attend et lit le
        cache rempli).
        """
        global _CATALOGUE_CACHE_MAPPING, _CATALOGUE_CACHE_TIMESTAMP

        ttl = settings.KARLIA_CATALOGUE_CACHE_TTL

        # 1er check sans lock : la plupart des requêtes seront cache HIT.
        if not force_refresh:
            cached = _CATALOGUE_CACHE_MAPPING
            cached_ts = _CATALOGUE_CACHE_TIMESTAMP
            if cached is not None and (time.time() - cached_ts) < ttl:
                logger.info(
                    "catalogue Karlia : cache HIT",
                    extra={"age_s": round(time.time() - cached_ts, 1),
                           "ttl_s": ttl, "nb_produits": len(cached)},
                )
                return cached, True

        # Cache miss : sous lock, re-check puis charge réseau si toujours
        # nécessaire (un autre coroutine a pu remplir le cache entre temps).
        lock = _get_catalogue_lock()
        async with lock:
            if not force_refresh:
                cached = _CATALOGUE_CACHE_MAPPING
                cached_ts = _CATALOGUE_CACHE_TIMESTAMP
                if cached is not None and (time.time() - cached_ts) < ttl:
                    return cached, True

            logger.info(
                "catalogue Karlia : cache MISS — chargement réseau",
                extra={"force_refresh": force_refresh, "ttl_s": ttl},
            )
            mapping = await self._charger_mapping_categories_reseau()
            _CATALOGUE_CACHE_MAPPING = mapping
            _CATALOGUE_CACHE_TIMESTAMP = time.time()
            return mapping, False

    # ── Karlia : bons de réception ────────────────────────────────────────

    async def _lister_suppliers_documents(self) -> List[dict]:
        """Pagine GET /suppliers-documents et renvoie TOUS les documents
        fournisseurs (tous types confondus). Sleep ENTRE deux pages,
        jamais après la dernière.

        Le re-filtrage par type est fait par l'appelant, parce qu'on a
        besoin de connaître les TYPES de tous les documents pour décider
        si un BR a déjà été facturé (id_document_next).
        """
        documents: List[dict] = []
        offset = 0
        endpoint = "/suppliers-documents"

        while True:
            params = {"limit": PAGE_SIZE, "offset": offset}
            try:
                body = await karlia._get(endpoint, params)
            except KarliaError as e:
                logger.error(
                    "karlia_factures_fournisseurs.suppliers_docs: erreur HTTP",
                    extra={
                        "endpoint": endpoint,
                        "offset": offset,
                        "status_code": e.status_code,
                        "message": e.message,
                    },
                )
                raise

            _check_karlia_body(endpoint, body, expect_data_list=True)
            data = body["data"]
            documents.extend(data)

            logger.info(
                "karlia_factures_fournisseurs.suppliers_docs: page chargée",
                extra={
                    "endpoint": endpoint,
                    "offset": offset,
                    "page_size": len(data),
                    "documents_total": len(documents),
                },
            )

            if len(data) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            await asyncio.sleep(DELAI_ENTRE_APPELS)

        return documents

    async def _detail_supplier_document(self, doc_id: int) -> dict:
        endpoint = f"/suppliers-documents/{doc_id}"
        try:
            body = await karlia._get(endpoint)
        except KarliaError as e:
            logger.error(
                "karlia_factures_fournisseurs.detail: erreur HTTP",
                extra={
                    "endpoint": endpoint,
                    "doc_id": doc_id,
                    "status_code": e.status_code,
                    "message": e.message,
                },
            )
            raise

        # Sur le détail, Karlia renvoie le document directement (sans clé
        # "data" — c'est un GET by id) ; on tolère les deux formes.
        if isinstance(body, dict) and "data" in body and isinstance(body["data"], dict):
            doc = body["data"]
        else:
            doc = body

        _check_karlia_body(endpoint, doc if isinstance(doc, dict) else body,
                           expect_data_list=False)
        if not isinstance(doc, dict):
            raise KarliaBodyError(endpoint, "détail BR non-dict", {"raw": body})
        return doc

    # ── Anti-doublon : pointage en mémoire ────────────────────────────────

    def _charger_pointage_pour_bls(
        self, db: Session, bl_ids: List[int]
    ) -> Dict[tuple, Decimal]:
        """Retourne { (id_bl_karlia, ligne_index) : quantite_facturee_cumulee }
        pour la liste de BR demandée. Les couples absents valent 0 (non
        renvoyés ici — l'appelant default à 0).
        """
        if not bl_ids:
            return {}
        rows = (
            db.query(FactureFournisseurPointage)
            .filter(FactureFournisseurPointage.id_bl_karlia.in_(bl_ids))
            .all()
        )
        return {
            (r.id_bl_karlia, r.ligne_index): r.quantite_facturee_cumulee or Decimal("0")
            for r in rows
        }

    # ── Construction des lignes facturables ───────────────────────────────

    async def lister_bons_reception_facturables(
        self,
        db: Session,
        id_fournisseur: Optional[int] = None,
        *,
        force_refresh: bool = False,
    ) -> List[dict]:
        """Retourne la liste des bons de réception facturables, groupés
        par fournisseur.

        Filtres appliqués (dans cet ordre) :
          1. id_type == 3 (re-filtré côté Python — le filtre serveur n'est
             pas fiable côté Karlia).
          2. Si id_document_next pointe un document de type facture
             (id_type=4) → BR exclu. Si le document cible n'est pas connu
             dans la liste chargée → exclu par sécurité (loggé).
          3. id_fournisseur si fourni.
          4. Au niveau ligne :
             a. section == "1"  → ligne ignorée (séparateur/titre).
             b. catégorie via mapping id_product → id_product_category :
                - id_product absent / 0 / non mappé → catégorie inconnue
                  → ligne INCLUSE (règle "lignes libres incluses par défaut").
                - catégorie ∈ CATEGORIES_EXCLUES → ligne exclue.
             c. restant = quantity_delivered − quantite_facturee_cumulee ;
                ligne exclue si restant ≤ 0.

        Paramètre `force_refresh` : si True, le cache du catalogue produits
        est bypassé (utilisé par le bouton "Rafraîchir" côté UI).

        Structure de retour : cf. docstring précédente.
        """
        # 1. Catalogue produits (catégories) — cache mémoire avec TTL.
        mapping_categories, cache_hit = await self.charger_mapping_categories(
            force_refresh=force_refresh,
        )
        # Sleep d'inter-phase uniquement si on vient de tirer le catalogue
        # depuis le réseau (sinon on enchaîne directement sur le listing).
        if not cache_hit:
            await asyncio.sleep(DELAI_ENTRE_APPELS)

        # 2. Liste exhaustive des documents fournisseurs (tous types).
        tous_documents = await self._lister_suppliers_documents()

        # Map id -> id_type pour résolution des id_document_next.
        type_par_id: Dict[int, int] = {}
        for d in tous_documents:
            d_id = _to_int_or_none(d.get("id"))
            d_type = _to_int_or_none(d.get("id_type"))
            if d_id is not None and d_type is not None:
                type_par_id[d_id] = d_type

        # 3. Re-filtrage côté Python : id_type == 3.
        bons_reception = [
            d for d in tous_documents
            if _to_int_or_none(d.get("id_type")) == KARLIA_SUPPLIER_TYPE_BON_RECEPTION
        ]
        logger.info(
            "lister_bons_reception_facturables: filtre id_type=3",
            extra={
                "total_documents": len(tous_documents),
                "bons_reception_apres_filtre_type": len(bons_reception),
            },
        )

        # 4. Filtre id_document_next pointant une facture.
        retenus: List[dict] = []
        for br in bons_reception:
            next_id = _to_int_or_none(br.get("id_document_next"))
            if next_id is None or next_id == 0:
                retenus.append(br)
                continue
            next_type = type_par_id.get(next_id)
            if next_type is None:
                logger.warning(
                    "BR exclu (id_document_next inconnu dans la liste)",
                    extra={
                        "id_bl": br.get("id"),
                        "numero": br.get("number"),
                        "id_document_next": next_id,
                    },
                )
                continue
            if next_type == KARLIA_SUPPLIER_TYPE_FACTURE:
                logger.info(
                    "BR exclu (déjà facturé côté Karlia)",
                    extra={
                        "id_bl": br.get("id"),
                        "numero": br.get("number"),
                        "id_facture_suivante": next_id,
                    },
                )
                continue
            retenus.append(br)

        # 5. Filtre fournisseur côté Python (le filtre serveur n'est pas fiable).
        if id_fournisseur is not None:
            avant = len(retenus)
            retenus = [
                br for br in retenus
                if _to_int_or_none(br.get("id_customer_supplier"))
                == id_fournisseur
            ]
            logger.info(
                "lister_bons_reception_facturables: filtre fournisseur",
                extra={
                    "id_fournisseur": id_fournisseur,
                    "avant": avant,
                    "apres": len(retenus),
                },
            )

        # 6. Détail de chaque BR retenu (products_list[]).
        bl_ids = [_to_int_or_none(br.get("id")) for br in retenus]
        bl_ids = [b for b in bl_ids if b is not None]
        pointage = self._charger_pointage_pour_bls(db, bl_ids)

        # Cache nom fournisseur via ClientCache (clé : karlia_id string).
        # Évite un appel /customers par fournisseur. Les fournisseurs Karlia
        # partagent l'identifiant 'customer/supplier' avec les clients dans
        # /customers ; on a déjà ClientCache, donc on l'utilise comme
        # source de vérité pour le nom affiché. Si absent, on tombera sur
        # le nom fourni par Karlia dans le document (customer_supplier_title).
        cache_clients = {
            cc.karlia_id: cc.nom
            for cc in db.query(ClientCache.karlia_id, ClientCache.nom).all()
        }

        # Sleep ENTRE deux appels de détail BR, jamais après le dernier
        # (le dernier sleep est inutile et ralentit le retour de 0.8 s).
        nb_detail_calls = 0
        groupes: Dict[int, dict] = {}
        for br in retenus:
            id_bl = _to_int_or_none(br.get("id"))
            if id_bl is None:
                continue
            id_fourn = _to_int_or_none(br.get("id_customer_supplier"))
            if id_fourn is None:
                logger.warning(
                    "BR ignoré (sans id_customer_supplier)",
                    extra={"id_bl": id_bl, "numero": br.get("number")},
                )
                continue

            if nb_detail_calls > 0:
                await asyncio.sleep(DELAI_ENTRE_APPELS)
            nb_detail_calls += 1

            # Détail (products_list).
            try:
                detail = await self._detail_supplier_document(id_bl)
            except KarliaBodyError as e:
                logger.error(
                    "BR ignoré (détail invalide)",
                    extra={
                        "id_bl": id_bl,
                        "numero": br.get("number"),
                        "erreur": e.message,
                    },
                )
                continue
            except KarliaError as e:
                logger.error(
                    "BR ignoré (HTTP error détail)",
                    extra={
                        "id_bl": id_bl,
                        "numero": br.get("number"),
                        "erreur": str(e),
                    },
                )
                continue

            products = detail.get("products_list") or []
            lignes_filtrees: List[dict] = []
            for idx, p in enumerate(products):
                # a. ignore lignes section ("1" → séparateur/titre)
                if str(p.get("section") or "") == "1":
                    logger.debug(
                        "Ligne BR ignorée (section)",
                        extra={"id_bl": id_bl, "ligne_index": idx},
                    )
                    continue

                # b. catégorie
                id_product = _to_int_or_none(p.get("id_product"))
                if id_product and id_product != 0:
                    categorie = mapping_categories.get(id_product)
                    if categorie is not None and categorie in CATEGORIES_EXCLUES:
                        logger.info(
                            "Ligne BR exclue (catégorie exclue)",
                            extra={
                                "id_bl": id_bl,
                                "ligne_index": idx,
                                "id_product": id_product,
                                "id_category": categorie,
                            },
                        )
                        continue
                # else: catégorie inconnue (lignes libres) → INCLUSE par défaut

                # c. quantité restante
                quantite_livree = _to_decimal(p.get("quantity_delivered"))
                deja_facturee = pointage.get((id_bl, idx), Decimal("0"))
                restante = quantite_livree - deja_facturee
                if restante <= 0:
                    logger.debug(
                        "Ligne BR ignorée (restant <= 0)",
                        extra={
                            "id_bl": id_bl,
                            "ligne_index": idx,
                            "quantite_livree": str(quantite_livree),
                            "deja_facturee": str(deja_facturee),
                        },
                    )
                    continue

                lignes_filtrees.append({
                    "ligne_index": idx,
                    "id_product": id_product,
                    "designation": (
                        p.get("title") or p.get("description") or ""
                    ),
                    "reference": p.get("reference"),
                    "quantite_livree": quantite_livree,
                    "quantite_deja_facturee": deja_facturee,
                    "quantite_restante": restante,
                    "prix_unitaire_ht": _to_decimal(p.get("price_without_tax")),
                    "id_vat": (
                        str(p.get("id_vat")) if p.get("id_vat") is not None else None
                    ),
                })

            if not lignes_filtrees:
                continue

            groupe = groupes.setdefault(id_fourn, {
                "id_fournisseur": id_fourn,
                "nom_fournisseur": (
                    cache_clients.get(str(id_fourn))
                    or br.get("customer_supplier_title")
                ),
                "bons_reception": [],
            })
            groupe["bons_reception"].append({
                "id_bl": id_bl,
                "numero": br.get("number"),
                "date": br.get("date"),
                "lignes": lignes_filtrees,
            })

        return list(groupes.values())

    # ── CRUD côté SGI ─────────────────────────────────────────────────────

    def _calculer_totaux(
        self, lignes: List[FactureFournisseurLigne]
    ) -> Dict[str, Decimal]:
        total_ht = Decimal("0")
        total_tva = Decimal("0")
        for ligne in lignes:
            taux = _taux_tva_pour_id_vat(ligne.id_vat_karlia) / Decimal("100")
            total_ht += ligne.total_ht or Decimal("0")
            total_tva += (ligne.total_ht or Decimal("0")) * taux
        # Arrondi 2 décimales pour la persistance.
        total_ht = total_ht.quantize(Decimal("0.01"))
        total_tva = total_tva.quantize(Decimal("0.01"))
        total_ttc = (total_ht + total_tva).quantize(Decimal("0.01"))
        return {"total_ht": total_ht, "total_tva": total_tva, "total_ttc": total_ttc}

    async def _construire_lignes_modeles(
        self,
        lignes_selectionnees: List[dict],
        *,
        ref_facture: str = "?",
        livraisons_precharge: Optional[Dict[int, Dict[int, Decimal]]] = None,
    ) -> List[FactureFournisseurLigne]:
        """Convertit les lignes posées par le client en modèles ORM, avec
        recontrôle anti-survalidation (quantité ≤ restant calculé à partir du
        détail BR + pointage). Lève ValueError sur dépassement.

        Si `livraisons_precharge` est fourni (cas creer_brouillon /
        mettre_a_jour_brouillon qui ont déjà appelé les détails BR pour la
        vérif fournisseur), on l'utilise tel quel — pas de 2ᵉ GET Karlia.
        Sinon on charge les détails ici (sleep ENTRE appels, pas après le
        dernier).

        Renseigne aussi `quantite_max_facturable` = restant à la création
        — snapshot consommé par l'écran d'édition pour éviter de rappeler
        /facturables.
        """
        # Indexation des restants par (id_bl_karlia, ligne_index) en
        # rappelant le pointage côté DB.
        from app.core.database import SessionLocal
        db = SessionLocal()
        try:
            bl_ids = sorted({_to_int_or_none(l["id_bl_karlia"]) for l in lignes_selectionnees})
            bl_ids = [b for b in bl_ids if b is not None]
            pointage = self._charger_pointage_pour_bls(db, bl_ids)
        finally:
            db.close()

        # Détails BR : on les recharge UNIQUEMENT si l'appelant ne nous les
        # a pas fournis. creer_brouillon les fournit (un seul aller-retour
        # pour la vérif fournisseur ET la construction des lignes).
        if livraisons_precharge is not None:
            livraisons = livraisons_precharge
        else:
            livraisons: Dict[int, Dict[int, Decimal]] = {}
            nb_calls = 0
            for id_bl in bl_ids:
                if nb_calls > 0:
                    await asyncio.sleep(DELAI_ENTRE_APPELS)
                nb_calls += 1
                try:
                    detail = await self._detail_supplier_document(id_bl)
                except (KarliaBodyError, KarliaError) as e:
                    raise ValueError(
                        f"Impossible de recontroler le BR {id_bl} ({ref_facture}) : {e}"
                    ) from e
                products = detail.get("products_list") or []
                livraisons[id_bl] = {
                    idx: _to_decimal(p.get("quantity_delivered"))
                    for idx, p in enumerate(products)
                }

        modeles: List[FactureFournisseurLigne] = []
        for l in lignes_selectionnees:
            id_bl = _to_int_or_none(l.get("id_bl_karlia"))
            ligne_index = _to_int_or_none(l.get("ligne_index"))
            quantite = _to_decimal(l.get("quantite"))
            if id_bl is None or ligne_index is None:
                raise ValueError(
                    "Ligne sélectionnée invalide (id_bl_karlia ou ligne_index manquant)"
                )

            livree = livraisons.get(id_bl, {}).get(ligne_index, Decimal("0"))
            deja = pointage.get((id_bl, ligne_index), Decimal("0"))
            restant = livree - deja
            if quantite <= 0 or quantite > restant:
                raise ValueError(
                    f"Ligne {id_bl}/{ligne_index} : quantité {quantite} hors borne "
                    f"(restant facturable = {restant}, livré = {livree}, "
                    f"déjà facturé = {deja})"
                )

            prix = _to_decimal(l.get("prix_unitaire_ht"))
            modeles.append(FactureFournisseurLigne(
                id_bl_karlia=id_bl,
                ligne_index=ligne_index,
                id_product_karlia=_to_int_or_none(l.get("id_product")),
                designation=str(l.get("designation") or "").strip()[:500] or "(ligne sans intitulé)",
                reference=(str(l["reference"])[:200] if l.get("reference") else None),
                quantite=quantite,
                prix_unitaire_ht=prix,
                id_vat_karlia=(str(l["id_vat"])[:10] if l.get("id_vat") is not None else None),
                total_ht=(quantite * prix).quantize(Decimal("0.01")),
                # Snapshot du restant à la création — borne max consommée
                # par l'écran d'édition sans rappeler /facturables.
                quantite_max_facturable=restant.quantize(Decimal("0.001")),
            ))
        return modeles

    async def creer_brouillon(
        self,
        db: Session,
        id_fournisseur: int,
        lignes_selectionnees: List[dict],
    ) -> FactureFournisseur:
        """Crée une facture fournisseur au statut 'brouillon'.

        Recontrôle côté serveur :
          - même fournisseur sur toutes les lignes (sinon ValueError),
          - quantité de chaque ligne ≤ restant facturable (recalculé à
            partir du détail BR + pointage cumulé). NE FAIT PAS confiance
            au payload front.

        Optim : UN SEUL GET /suppliers-documents/{id} par BR distinct
        — son résultat sert à la fois à la vérification du fournisseur
        ET au recontrôle des quantités.

        Ne touche PAS la table pointage à la création.
        """
        if not lignes_selectionnees:
            raise ValueError("Aucune ligne sélectionnée")

        # Liste des BR distincts cités dans la sélection.
        bl_ids = sorted({_to_int_or_none(l.get("id_bl_karlia")) for l in lignes_selectionnees})
        bl_ids = [b for b in bl_ids if b is not None]

        # Un seul aller-retour par BR : vérif fournisseur ET livraisons.
        livraisons: Dict[int, Dict[int, Decimal]] = {}
        nom_fournisseur: Optional[str] = None
        nb_calls = 0
        for id_bl in bl_ids:
            if nb_calls > 0:
                await asyncio.sleep(DELAI_ENTRE_APPELS)
            nb_calls += 1
            try:
                detail = await self._detail_supplier_document(id_bl)
            except (KarliaBodyError, KarliaError) as e:
                raise ValueError(f"Impossible de relire BR {id_bl} : {e}") from e
            fourn_br = _to_int_or_none(detail.get("id_customer_supplier"))
            if fourn_br != id_fournisseur:
                raise ValueError(
                    f"Le BR {id_bl} appartient au fournisseur {fourn_br}, "
                    f"pas à {id_fournisseur}"
                )
            if not nom_fournisseur:
                nom_fournisseur = detail.get("customer_supplier_title")
            products = detail.get("products_list") or []
            livraisons[id_bl] = {
                idx: _to_decimal(p.get("quantity_delivered"))
                for idx, p in enumerate(products)
            }

        # Si pas de nom dans le BR, repli sur ClientCache.
        if not nom_fournisseur:
            cc = db.query(ClientCache.nom).filter(
                ClientCache.karlia_id == str(id_fournisseur)
            ).first()
            if cc:
                nom_fournisseur = cc[0]

        # Construction lignes + recontrôle. Pas de re-GET grâce à
        # livraisons_precharge.
        modeles = await self._construire_lignes_modeles(
            lignes_selectionnees,
            ref_facture="(brouillon)",
            livraisons_precharge=livraisons,
        )

        facture = FactureFournisseur(
            id_fournisseur_karlia=id_fournisseur,
            nom_fournisseur=nom_fournisseur,
            statut="brouillon",
        )
        for m in modeles:
            facture.lignes.append(m)

        totaux = self._calculer_totaux(modeles)
        facture.total_ht = totaux["total_ht"]
        facture.total_tva = totaux["total_tva"]
        facture.total_ttc = totaux["total_ttc"]

        db.add(facture)
        db.commit()
        db.refresh(facture)
        logger.info(
            "facture fournisseur créée (brouillon)",
            extra={
                "facture_id": facture.id,
                "id_fournisseur": id_fournisseur,
                "nb_lignes": len(modeles),
                "total_ht": str(facture.total_ht),
                "total_ttc": str(facture.total_ttc),
            },
        )
        return facture

    async def mettre_a_jour_brouillon(
        self,
        db: Session,
        id_facture: int,
        lignes_selectionnees: List[dict],
    ) -> FactureFournisseur:
        """Remplace les lignes d'un brouillon et recalcule les totaux.
        Refuse si statut != 'brouillon'.

        Optim identique à creer_brouillon : un seul GET par BR distinct.
        """
        facture = (
            db.query(FactureFournisseur)
            .options(joinedload(FactureFournisseur.lignes))
            .filter(FactureFournisseur.id == id_facture)
            .first()
        )
        if facture is None:
            raise LookupError(f"Facture fournisseur {id_facture} introuvable")
        if facture.statut != "brouillon":
            raise ValueError(
                f"Facture {id_facture} non modifiable (statut '{facture.statut}')"
            )
        if not lignes_selectionnees:
            raise ValueError("Aucune ligne sélectionnée")

        # Un seul GET par BR : vérif cohérence fournisseur ET livraisons.
        bl_ids = sorted({_to_int_or_none(l.get("id_bl_karlia")) for l in lignes_selectionnees})
        bl_ids = [b for b in bl_ids if b is not None]
        livraisons: Dict[int, Dict[int, Decimal]] = {}
        nb_calls = 0
        for id_bl in bl_ids:
            if nb_calls > 0:
                await asyncio.sleep(DELAI_ENTRE_APPELS)
            nb_calls += 1
            try:
                detail = await self._detail_supplier_document(id_bl)
            except (KarliaBodyError, KarliaError) as e:
                raise ValueError(f"Impossible de relire BR {id_bl} : {e}") from e
            fourn_br = _to_int_or_none(detail.get("id_customer_supplier"))
            if fourn_br != facture.id_fournisseur_karlia:
                raise ValueError(
                    f"Le BR {id_bl} appartient au fournisseur {fourn_br}, "
                    f"pas à {facture.id_fournisseur_karlia}"
                )
            products = detail.get("products_list") or []
            livraisons[id_bl] = {
                idx: _to_decimal(p.get("quantity_delivered"))
                for idx, p in enumerate(products)
            }

        modeles = await self._construire_lignes_modeles(
            lignes_selectionnees,
            ref_facture=f"#{facture.id} (update)",
            livraisons_precharge=livraisons,
        )

        # Remplacer les lignes (cascade=all,delete-orphan).
        facture.lignes.clear()
        db.flush()
        for m in modeles:
            facture.lignes.append(m)

        totaux = self._calculer_totaux(modeles)
        facture.total_ht = totaux["total_ht"]
        facture.total_tva = totaux["total_tva"]
        facture.total_ttc = totaux["total_ttc"]

        db.commit()
        db.refresh(facture)
        logger.info(
            "facture fournisseur mise à jour (brouillon)",
            extra={
                "facture_id": facture.id,
                "nb_lignes": len(modeles),
                "total_ht": str(facture.total_ht),
            },
        )
        return facture

    async def valider_facture(
        self,
        db: Session,
        id_facture: int,
    ) -> FactureFournisseur:
        """Valide une facture brouillon : incrémente le pointage par ligne
        et passe le statut à 'validee'. Transaction atomique.

        N'appelle PAS Karlia (émission non disponible). Les colonnes
        id_suppliers_document_karlia et statut_emission_karlia restent NULL.
        """
        facture = (
            db.query(FactureFournisseur)
            .options(joinedload(FactureFournisseur.lignes))
            .filter(FactureFournisseur.id == id_facture)
            .first()
        )
        if facture is None:
            raise LookupError(f"Facture fournisseur {id_facture} introuvable")
        if facture.statut != "brouillon":
            raise ValueError(
                f"Facture {id_facture} déjà validée ou non brouillon "
                f"(statut '{facture.statut}')"
            )
        if not facture.lignes:
            raise ValueError(f"Facture {id_facture} sans ligne — validation refusée")

        # Pour chaque ligne distincte (id_bl, ligne_index), recharger la
        # quantity_delivered depuis le détail BR (si pointage à créer) et
        # vérifier que le cumul ne dépasse pas la livraison.
        bl_index_couples = {(l.id_bl_karlia, l.ligne_index) for l in facture.lignes}
        bl_ids = sorted({c[0] for c in bl_index_couples})

        # Détails BR (un seul GET par BR), uniquement si certains pointages
        # sont absents — sinon on peut s'appuyer sur quantite_livree stockée.
        existants = {
            (p.id_bl_karlia, p.ligne_index): p
            for p in db.query(FactureFournisseurPointage)
            .filter(FactureFournisseurPointage.id_bl_karlia.in_(bl_ids))
            .all()
        }
        livraisons_par_br: Dict[int, Dict[int, Decimal]] = {}
        nb_calls = 0
        for id_bl in bl_ids:
            besoin_detail = any(
                (id_bl, idx) not in existants for (_b, idx) in bl_index_couples
                if _b == id_bl
            )
            if not besoin_detail:
                continue
            if nb_calls > 0:
                await asyncio.sleep(DELAI_ENTRE_APPELS)
            nb_calls += 1
            try:
                detail = await self._detail_supplier_document(id_bl)
            except (KarliaBodyError, KarliaError) as e:
                raise ValueError(f"Validation impossible — BR {id_bl} : {e}") from e
            products = detail.get("products_list") or []
            livraisons_par_br[id_bl] = {
                idx: _to_decimal(p.get("quantity_delivered"))
                for idx, p in enumerate(products)
            }

        try:
            for ligne in facture.lignes:
                cle = (ligne.id_bl_karlia, ligne.ligne_index)
                pointage = existants.get(cle)
                if pointage is None:
                    livree = livraisons_par_br.get(
                        ligne.id_bl_karlia, {}
                    ).get(ligne.ligne_index)
                    if livree is None:
                        raise ValueError(
                            f"Quantité livrée introuvable pour BR "
                            f"{ligne.id_bl_karlia} ligne {ligne.ligne_index}"
                        )
                    if ligne.quantite > livree:
                        raise ValueError(
                            f"Ligne {ligne.id_bl_karlia}/{ligne.ligne_index} : "
                            f"quantité facturée ({ligne.quantite}) supérieure "
                            f"à la livraison ({livree})"
                        )
                    pointage = FactureFournisseurPointage(
                        id_bl_karlia=ligne.id_bl_karlia,
                        ligne_index=ligne.ligne_index,
                        quantite_livree=livree,
                        quantite_facturee_cumulee=ligne.quantite,
                    )
                    db.add(pointage)
                    existants[cle] = pointage
                else:
                    nouveau_cumul = (
                        (pointage.quantite_facturee_cumulee or Decimal("0"))
                        + ligne.quantite
                    )
                    if nouveau_cumul > (pointage.quantite_livree or Decimal("0")):
                        raise ValueError(
                            f"Ligne {ligne.id_bl_karlia}/{ligne.ligne_index} : "
                            f"cumul facturé ({nouveau_cumul}) dépasse la "
                            f"livraison ({pointage.quantite_livree})"
                        )
                    pointage.quantite_facturee_cumulee = nouveau_cumul

            facture.statut = "validee"
            db.commit()
            db.refresh(facture)
        except Exception:
            db.rollback()
            raise

        logger.info(
            "facture fournisseur validée",
            extra={
                "facture_id": facture.id,
                "id_fournisseur": facture.id_fournisseur_karlia,
                "nb_lignes": len(facture.lignes),
                "total_ttc": str(facture.total_ttc),
            },
        )
        return facture

    def supprimer_brouillon(self, db: Session, id_facture: int) -> None:
        """Supprime un brouillon. Les lignes sont supprimées par CASCADE."""
        facture = (
            db.query(FactureFournisseur)
            .filter(FactureFournisseur.id == id_facture)
            .first()
        )
        if facture is None:
            raise LookupError(f"Facture fournisseur {id_facture} introuvable")
        if facture.statut != "brouillon":
            raise ValueError(
                f"Suppression refusée : facture {id_facture} au statut "
                f"'{facture.statut}'"
            )
        db.delete(facture)
        db.commit()
        logger.info("facture fournisseur supprimée (brouillon)", extra={
            "facture_id": id_facture,
        })


# Singleton (similaire à `karlia` et `karlia_devis_service`).
karlia_factures_fournisseurs_service = KarliaFacturesFournisseursService()
