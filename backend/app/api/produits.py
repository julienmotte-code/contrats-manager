"""Routes produits — Cache des articles Karlia"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.core.database import get_db
from app.models.models import ArticleCache
from app.services.karlia_service import karlia, KarliaError

router = APIRouter()


@router.get("")
async def lister_produits(
    recherche: Optional[str] = Query(None),
    source: str = Query("cache"),
    db: Session = Depends(get_db),
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
    articles = query.order_by(ArticleCache.designation).limit(100).all()
    return {"source": "cache", "data": [
        {"karlia_id": a.karlia_id, "reference": a.reference, "designation": a.designation,
         "prix_unitaire_ht": float(a.prix_unitaire_ht) if a.prix_unitaire_ht else None,
         "unite": a.unite, "taux_tva": float(a.taux_tva)}
        for a in articles
    ]}


@router.post("/synchro")
async def synchroniser_produits(db: Session = Depends(get_db)):
    try:
        result = await karlia.lister_produits(limit=500)
        count = 0
        for p in result.get("data", []):
            karlia_id = str(p["id"])
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
            }
            if existing:
                for k, v in data.items():
                    setattr(existing, k, v)
            else:
                db.add(ArticleCache(**data))
            count += 1
        db.commit()
        return {"message": f"{count} articles synchronisés"}
    except KarliaError as e:
        raise HTTPException(502, f"Erreur Karlia : {e.message}")


def _formater_produit_karlia(p: dict) -> dict:
    prix = p.get("sell_price", {})
    return {
        "karlia_id": str(p.get("id", "")),
        "reference": p.get("reference", ""),
        "designation": p.get("title", p.get("name", "")),
        "prix_unitaire_ht": prix.get("price") if isinstance(prix, dict) else None,
        "unite": p.get("unit", ""),
    }
