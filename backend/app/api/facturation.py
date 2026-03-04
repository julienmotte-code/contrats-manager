from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.core.database import get_db
from app.models.models import Contrat, PlanFacturation, IndiceRevision, Utilisateur
from app.api.auth import get_current_user
from app.services.karlia_service import karlia
from app.services.revision_service import (
    calculer_revision, verifier_indices_disponibles, get_regle_revision, FAMILLES_CONTRAT
)
from datetime import date
from decimal import Decimal
from typing import Optional, List
import uuid

router = APIRouter()

@router.get("/apercu/{annee}")
def apercu_facturation(annee: int, famille: Optional[str] = None, db: Session = Depends(get_db)):
    """Liste les factures à émettre pour une année donnée."""
    annee_courante = date.today().year
    q = db.query(PlanFacturation).join(Contrat).filter(
        PlanFacturation.annee_facturation == annee,
        PlanFacturation.statut.in_(["PLANIFIEE", "CALCULEE"]),
        Contrat.statut == "EN_COURS",
    )
    if famille:
        q = q.filter(Contrat.famille_contrat == famille.upper())
    plans = q.all()

    result = []
    for p in plans:
        contrat = p.contrat
        regle = get_regle_revision(contrat.famille_contrat or "COSOLUCE")
        verif = verifier_indices_disponibles(db, contrat.famille_contrat or "COSOLUCE", annee) if annee > annee_courante - 1 else {"ok": True}

        result.append({
            "plan_id": str(p.id),
            "contrat_id": str(contrat.id),
            "numero_contrat": contrat.numero_contrat,
            "client_nom": contrat.client_nom,
            "famille_contrat": contrat.famille_contrat,
            "annee": annee,
            "date_echeance": str(p.date_echeance),
            "montant_prevu": float(p.montant_ht_prevu or 0),
            "montant_revise": float(p.montant_revise_ht) if p.montant_revise_ht else None,
            "montant_annuel_precedent": float(p.montant_annuel_precedent) if p.montant_annuel_precedent else float(contrat.montant_annuel_ht),
            "statut": p.statut,
            "regle_revision": regle,
            "indices_ok": verif.get("ok", True),
            "indices_message": verif.get("message", ""),
            "facturable": annee <= annee_courante,
        })
    return {"data": result, "annee_courante": annee_courante}

@router.post("/calculer")
async def calculer_factures(
    body: dict,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    """
    Calcule les montants révisés pour une liste de plans.
    Pour Digitech: nouveau_montant requis dans body.
    """
    annee = body.get("annee", date.today().year)
    plan_ids = body.get("plan_ids", [])
    nouveaux_montants = body.get("nouveaux_montants", {})  # {plan_id: montant} pour Digitech

    annee_courante = date.today().year
    if annee > annee_courante:
        raise HTTPException(400, f"Impossible de calculer pour une année future ({annee})")

    resultats = []
    for plan_id in plan_ids:
        plan = db.query(PlanFacturation).filter(PlanFacturation.id == plan_id).first()
        if not plan:
            resultats.append({"plan_id": plan_id, "ok": False, "message": "Plan non trouvé"})
            continue

        contrat = plan.contrat
        famille = contrat.famille_contrat or "COSOLUCE"

        # Montant de référence = montant précédent ou montant annuel du contrat
        montant_precedent = Decimal(str(plan.montant_annuel_precedent or contrat.montant_annuel_ht))

        # Montant manuel pour Digitech
        nouveau_montant = None
        if plan_id in nouveaux_montants:
            nouveau_montant = Decimal(str(nouveaux_montants[plan_id]))

        # Première année = pas de révision
        if annee == contrat.date_debut.year:
            montant_revise = Decimal(str(plan.montant_ht_prevu or contrat.montant_annuel_ht))
            plan.montant_revise_ht = montant_revise
            plan.taux_revision = Decimal("1.000000")
            plan.statut = "CALCULEE"
            db.commit()
            resultats.append({"plan_id": plan_id, "ok": True, "montant_revise": float(montant_revise), "message": "Première année — pas de révision"})
            continue

        result = calculer_revision(db, famille, annee, montant_precedent, nouveau_montant)
        if not result["ok"]:
            resultats.append({"plan_id": plan_id, "ok": False, "message": result["message"]})
            continue

        plan.montant_annuel_precedent = montant_precedent
        plan.montant_revise_ht = result["montant_revise"]
        plan.taux_revision = result["taux_revision"]
        if result.get("indice_n1"):
            plan.indice_calcul_id = result["indice_n1"].id
        plan.statut = "CALCULEE"
        db.commit()

        resultats.append({
            "plan_id": plan_id,
            "ok": True,
            "montant_precedent": float(montant_precedent),
            "montant_revise": float(result["montant_revise"]),
            "taux_revision": float(result["taux_revision"]),
            "message": result["message"],
        })

    return {"resultats": resultats}

@router.post("/lancer")
async def lancer_facturation(
    body: dict,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    """Émet les factures pour une liste de plan_ids."""
    annee = body.get("annee", date.today().year)
    plan_ids = body.get("plan_ids", [])

    annee_courante = date.today().year
    if annee > annee_courante:
        raise HTTPException(400, f"Impossible de facturer une année future ({annee})")

    lot_id = str(uuid.uuid4())
    factures_a_emettre = []

    for plan_id in plan_ids:
        plan = db.query(PlanFacturation).filter(PlanFacturation.id == plan_id).first()
        if not plan or plan.statut not in ["PLANIFIEE", "CALCULEE"]:
            continue

        contrat = plan.contrat
        montant_ht = float(plan.montant_revise_ht or plan.montant_ht_prevu or contrat.montant_annuel_ht)
        article_principal = next((a for a in contrat.articles if a.rang == 0), None)

        lignes = [{
            "id_product": article_principal.article_karlia_id if article_principal else None,
            "description": article_principal.designation if article_principal else contrat.numero_contrat,
            "unit_price": montant_ht,
            "quantity": 1,
            "vat_rate": float(article_principal.taux_tva) if article_principal else 20.0,
        }]

        factures_a_emettre.append({
            "plan_id": plan_id,
            "contrat_id": str(contrat.id),
            "client_karlia_id": contrat.client_karlia_id,
            "reference_contrat": contrat.numero_contrat,
            "date_echeance": plan.date_echeance,
            "montant_ht": montant_ht,
            "lignes": lignes,
            "description": f"Facturation {annee} — Contrat {contrat.numero_contrat}",
        })

    if not factures_a_emettre:
        return {"lot_id": lot_id, "traites": 0, "emises": 0, "erreurs": 0, "resultats": []}

    resultats_karlia = await karlia.traitement_lot_factures(factures_a_emettre)

    emises = erreurs = 0
    for r in resultats_karlia:
        plan = db.query(PlanFacturation).filter(PlanFacturation.id == r["plan_id"]).first()
        if not plan:
            continue
        if r["succes"]:
            plan.statut = "EMISE"
            plan.facture_karlia_id = r.get("karlia_doc_id")
            plan.facture_karlia_ref = r.get("karlia_doc_ref")
            # Mettre à jour montant_annuel_precedent pour l'année suivante
            plan.montant_annuel_precedent = plan.montant_revise_ht or plan.montant_ht_prevu
            emises += 1
        else:
            plan.statut = "ERREUR"
            plan.erreur_message = r.get("erreur")
            erreurs += 1
        db.commit()

    return {
        "lot_id": lot_id,
        "traites": len(factures_a_emettre),
        "emises": emises,
        "erreurs": erreurs,
        "resultats": resultats_karlia,
    }

@router.get("/lot/{lot_id}")
def statut_lot(lot_id: str):
    return {"lot_id": lot_id, "statut": "TERMINE"}
