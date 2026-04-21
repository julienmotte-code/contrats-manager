"""
Routes API — Dashboard
GET /api/dashboard/stats → Statistiques tableau de bord
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.models.models import Contrat, Commande
from app.services.revision_service import FAMILLES_CONTRAT

router = APIRouter()

# Mapping code → label pour les familles
FAMILLE_LABELS = {f["code"]: f["label"] for f in FAMILLES_CONTRAT}


@router.get("/stats")
def dashboard_stats(db: Session = Depends(get_db)):
    """
    Retourne les statistiques du tableau de bord :
    - Contrats actifs groupés par famille
    - Commandes groupées par statut
    """

    # ── Contrats actifs par famille ──────────────────────────────
    contrats_query = (
        db.query(
            Contrat.famille_contrat,
            func.count(Contrat.id).label("total"),
        )
        .filter(Contrat.statut.in_(["EN_COURS", "A_RENOUVELER"]))
        .group_by(Contrat.famille_contrat)
        .all()
    )

    contrats_par_famille = []
    total_contrats = 0
    for famille_code, count in contrats_query:
        label = FAMILLE_LABELS.get(famille_code, famille_code or "Non défini")
        contrats_par_famille.append({
            "code": famille_code or "AUTRE",
            "label": label,
            "total": count,
        })
        total_contrats += count

    # Trier par total décroissant
    contrats_par_famille.sort(key=lambda x: x["total"], reverse=True)

    # ── Commandes par statut ─────────────────────────────────────
    commandes_query = (
        db.query(
            Commande.statut,
            func.count(Commande.id).label("total"),
        )
        .group_by(Commande.statut)
        .all()
    )

    commandes_dict = {statut: count for statut, count in commandes_query}

    commandes_par_statut = {
        "nouvelles": commandes_dict.get("nouvelle", 0),
        "a_planifier": commandes_dict.get("a_planifier", 0),
        "planifiees": commandes_dict.get("planifiee", 0),
        "terminees": commandes_dict.get("deployee", 0) + commandes_dict.get("terminee", 0),
        "total": sum(commandes_dict.values()),
    }

    return {
        "contrats_par_famille": contrats_par_famille,
        "total_contrats": total_contrats,
        "commandes_par_statut": commandes_par_statut,
    }
