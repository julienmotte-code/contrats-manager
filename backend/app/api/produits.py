"""Routes produits — Cache des articles Karlia"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.core.security import require_authenticated, require_role
from app.models.models import ArticleCache
from app.services.karlia_service import karlia, KarliaError

logger = logging.getLogger(__name__)

router = APIRouter()

# Seuil minimal d'articles reçus de Karlia pour déclencher la désactivation des
# obsolètes. Si Karlia renvoie moins (réponse partielle, erreur silencieuse,
# coupure réseau), on n'ose PAS désactiver — risque de tout invalider sur une
# anomalie temporaire. 50 = très en-dessous des ~400 attendus, suffisant pour
# détecter une réponse manifestement tronquée.
SEUIL_REPONSE_PLAUSIBLE = 50


@router.get("")
async def lister_produits(
    recherche: Optional[str] = Query(None),
    source: str = Query("cache"),
    db: Session = Depends(get_db),
    current_user = Depends(require_authenticated),
):
    if source == "karlia":
        try:
            result = await karlia.lister_produits(recherche=recherche)
            return {"source": "karlia", "data": [_formater_produit_karlia(p) for p in result.get("data", [])]}
        except KarliaError as e:
            raise HTTPException(502, f"Erreur Karlia : {e.message}")

    query = db.query(ArticleCache).filter(ArticleCache.actif == True)
    if recherche:
        query = query.filter(ArticleCache.designation.ilike(f"%{recherche}%"))
    articles = query.order_by(ArticleCache.designation).limit(1000).all()
    return {"source": "cache", "data": [
        {"karlia_id": a.karlia_id, "reference": a.reference, "designation": a.designation,
         "prix_unitaire_ht": float(a.prix_unitaire_ht) if a.prix_unitaire_ht else None,
         "unite": a.unite, "taux_tva": float(a.taux_tva)}
        for a in articles
    ]}


@router.post("/synchro")
async def synchroniser_produits(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    try:
        result = await karlia.lister_produits(limit=500)
        produits_recus = result.get("data", [])
        ids_karlia_recus = set()
        count = 0
        for p in produits_recus:
            karlia_id = str(p["id"])
            ids_karlia_recus.add(karlia_id)
            existing = db.query(ArticleCache).filter(ArticleCache.karlia_id == karlia_id).first()
            prix = p.get("sell_price", {})
            prix_ht = prix.get("price") if isinstance(prix, dict) else None
            data = {
                "karlia_id": karlia_id,
                "reference": p.get("reference", ""),
                "designation": p.get("title", p.get("name", "")),
                "prix_unitaire_ht": prix_ht,
                "unite": p.get("unit", ""),
                "actif": True,
                # Catégorie Karlia : on filtre toujours sur id_product_category (instable
                # côté libellé). Karlia renvoie id_product_category en str ; on convertit
                # en int. NULL accepté si produit sans catégorie au catalogue.
                "id_product_category": _to_int_or_none(p.get("id_product_category")),
                "product_category": p.get("product_category") or None,
            }
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
            else:
                db.add(ArticleCache(**data))
            count += 1

        # Garde anti-réponse-partielle : on ne désactive les obsolètes QUE si la
        # réponse Karlia est manifestement complète. En dessous du seuil, on logge
        # un warning et on saute la désactivation — éviter d'invalider tout le
        # cache sur une réponse Karlia dégradée (timeout, rate-limit, panne).
        desactives = 0
        if len(produits_recus) >= SEUIL_REPONSE_PLAUSIBLE:
            obsoletes = db.query(ArticleCache).filter(
                ArticleCache.actif == True,
                ~ArticleCache.karlia_id.in_(ids_karlia_recus),
            ).all()
            for a in obsoletes:
                a.actif = False
            desactives = len(obsoletes)
            logger.info(
                f"Synchro articles : {count} ajoutés/maj, {desactives} désactivés (absents de Karlia)"
            )
        else:
            logger.warning(
                f"Synchro articles : Karlia a renvoyé {len(produits_recus)} produits "
                f"(< seuil {SEUIL_REPONSE_PLAUSIBLE}), désactivation des obsolètes SKIPPED par sécurité"
            )

        db.commit()
        return {
            "message": f"{count} articles synchronisés, {desactives} désactivés",
            "ajoutes_ou_majs": count,
            "desactives": desactives,
        }
    except KarliaError as e:
        raise HTTPException(502, f"Erreur Karlia : {e.message}")


def _to_int_or_none(v):
    """
    Convertit une valeur Karlia (str/int/None) en int, ou None si vide/invalide.

    Convention : 0 / "0" sont traités comme NULL — Karlia renvoie parfois
    id_product_category="0" pour les produits non catégorisés, on stocke NULL
    plutôt qu'un entier 0 qui n'a pas de sémantique métier.
    """
    if v is None or v == "":
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return None if n == 0 else n


def _formater_produit_karlia(p: dict) -> dict:
    prix = p.get("sell_price", {})
    return {
        "karlia_id": str(p.get("id", "")),
        "reference": p.get("reference", ""),
        "designation": p.get("title", p.get("name", "")),
        "prix_unitaire_ht": prix.get("price") if isinstance(prix, dict) else None,
        "unite": p.get("unit", ""),
    }
