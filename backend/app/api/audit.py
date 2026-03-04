"""
Routes API — Audit et autovalidation
GET /api/audit/contrat/{id}         → Santé d'un contrat
GET /api/audit/facturation/{annee}  → Cohérence d'une année
GET /api/audit/global               → Vue globale tous contrats EN_COURS
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.models.models import Contrat, Utilisateur
from app.api.auth import get_current_user
from app.services.validation_service import valider_contrat, auditer_annee_facturation

router = APIRouter()


@router.get("/contrat/{contrat_id}")
def audit_contrat(
    contrat_id: str,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    contrat = db.query(Contrat).filter(Contrat.id == contrat_id).first()
    if not contrat:
        raise HTTPException(404, "Contrat non trouvé")
    return valider_contrat(db, contrat)


@router.get("/facturation/{annee}")
def audit_facturation(
    annee: int,
    famille: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    rapport = auditer_annee_facturation(db, annee)
    if famille:
        rapport["contrats"] = [c for c in rapport["contrats"] if c["famille"] == famille.upper()]
        rapport["total_contrats"] = len(rapport["contrats"])
        rapport["erreurs"] = sum(sum(1 for a in c["alertes"] if a["niveau"] == "ERREUR") for c in rapport["contrats"])
        rapport["warnings"] = sum(sum(1 for a in c["alertes"] if a["niveau"] == "WARNING") for c in rapport["contrats"])
        rapport["sains"] = sum(1 for c in rapport["contrats"] if c["sain"])
    return rapport


@router.get("/global")
def audit_global(
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user),
):
    contrats = db.query(Contrat).filter(Contrat.statut == "EN_COURS").all()
    resultats = []
    total_erreurs = total_warnings = 0

    for contrat in contrats:
        audit = valider_contrat(db, contrat)
        nb_e = sum(1 for a in audit["alertes"] if a["niveau"] == "ERREUR")
        nb_w = sum(1 for a in audit["alertes"] if a["niveau"] == "WARNING")
        total_erreurs += nb_e
        total_warnings += nb_w
        resultats.append({
            "contrat_id": str(contrat.id),
            "numero_contrat": contrat.numero_contrat,
            "client_nom": contrat.client_nom,
            "famille": contrat.famille_contrat,
            "sain": audit["sain"],
            "nb_erreurs": nb_e,
            "nb_warnings": nb_w,
            "alertes": [a for a in audit["alertes"] if a["niveau"] != "INFO"],
        })

    resultats.sort(key=lambda x: (-x["nb_erreurs"], -x["nb_warnings"]))

    return {
        "total_contrats": len(contrats),
        "contrats_sains": sum(1 for r in resultats if r["sain"]),
        "contrats_en_erreur": sum(1 for r in resultats if r["nb_erreurs"] > 0),
        "contrats_en_warning": sum(1 for r in resultats if r["nb_warnings"] > 0 and r["nb_erreurs"] == 0),
        "total_erreurs": total_erreurs,
        "total_warnings": total_warnings,
        "contrats": resultats,
    }
