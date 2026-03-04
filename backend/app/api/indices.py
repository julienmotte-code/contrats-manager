from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.core.database import get_db
from app.models.models import IndiceRevision
from app.api.auth import get_current_user
from app.models.models import Utilisateur
from app.services.revision_service import FAMILLES_CONTRAT
from datetime import date
from typing import Optional
import uuid

router = APIRouter()

@router.get("/familles")
def lister_familles():
    """Liste les familles de contrats et leurs règles de révision."""
    return {"data": FAMILLES_CONTRAT}

@router.get("")
def lister_indices(
    mois: Optional[str] = None,
    annee: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Liste les indices Syntec avec filtres optionnels."""
    q = db.query(IndiceRevision)
    if mois:
        q = q.filter(IndiceRevision.mois == mois.upper())
    if annee:
        q = q.filter(IndiceRevision.annee == annee)
    indices = q.order_by(desc(IndiceRevision.annee), IndiceRevision.mois).all()
    return {
        "data": [{
            "id": str(i.id),
            "date_publication": str(i.date_publication),
            "annee": i.annee,
            "mois": i.mois,
            "famille": i.famille,
            "valeur": float(i.valeur),
            "commentaire": i.commentaire,
        } for i in indices]
    }

@router.get("/courant")
def indice_courant(db: Session = Depends(get_db)):
    """Retourne le dernier indice Syntec Août."""
    indice = db.query(IndiceRevision).filter(
        IndiceRevision.mois == "AOUT"
    ).order_by(desc(IndiceRevision.annee)).first()
    if not indice:
        return {"indice": None}
    return {
        "indice": {
            "id": str(indice.id),
            "date_publication": str(indice.date_publication),
            "annee": indice.annee,
            "mois": indice.mois,
            "valeur": float(indice.valeur),
        }
    }

@router.post("")
def creer_indice(
    data: dict,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    """Crée un nouvel indice Syntec."""
    mois = data.get("mois", "AOUT").upper()
    annee = data.get("annee")
    valeur = data.get("valeur")

    if not annee or not valeur:
        raise HTTPException(400, "annee et valeur sont obligatoires")
    if mois not in ["AOUT", "OCTOBRE", "AUTRE"]:
        raise HTTPException(400, "mois doit être AOUT, OCTOBRE ou AUTRE")

    # Vérifier doublon
    existant = db.query(IndiceRevision).filter(
        IndiceRevision.annee == annee,
        IndiceRevision.mois == mois
    ).first()
    if existant:
        raise HTTPException(400, f"Un indice Syntec {mois} {annee} existe déjà (valeur: {existant.valeur})")

    # Date de publication selon le mois
    mois_num = 8 if mois == "AOUT" else (10 if mois == "OCTOBRE" else 1)
    date_pub = date(int(annee), mois_num, 1)

    indice = IndiceRevision(
        id=uuid.uuid4(),
        date_publication=date_pub,
        annee=int(annee),
        mois=mois,
        famille=data.get("famille", "SYNTEC"),
        valeur=valeur,
        commentaire=data.get("commentaire", ""),
        created_by=current_user.login,
    )
    db.add(indice)
    db.commit()
    db.refresh(indice)
    return {"id": str(indice.id), "annee": indice.annee, "mois": indice.mois, "valeur": float(indice.valeur)}

@router.put("/{indice_id}")
def modifier_indice(
    indice_id: str,
    data: dict,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    """Modifie un indice existant."""
    indice = db.query(IndiceRevision).filter(IndiceRevision.id == indice_id).first()
    if not indice:
        raise HTTPException(404, "Indice non trouvé")
    if "valeur" in data:
        indice.valeur = data["valeur"]
    if "commentaire" in data:
        indice.commentaire = data["commentaire"]
    db.commit()
    return {"id": str(indice.id), "valeur": float(indice.valeur)}

@router.delete("/{indice_id}")
def supprimer_indice(
    indice_id: str,
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    """Supprime un indice."""
    from app.models.models import Contrat, PlanFacturation
    indice = db.query(IndiceRevision).filter(IndiceRevision.id == indice_id).first()
    if not indice:
        raise HTTPException(404, "Indice non trouvé")
    # Délier toutes les références avant suppression
    from sqlalchemy import text
    db.query(Contrat).filter(Contrat.indice_reference_id == indice_id).update({"indice_reference_id": None})
    db.query(PlanFacturation).filter(PlanFacturation.indice_calcul_id == indice_id).update({"indice_calcul_id": None})
    db.execute(text("UPDATE lots_facturation SET indice_utilise_id = NULL WHERE indice_utilise_id = :id"), {"id": indice_id})
    db.commit()
    db.delete(indice)
    db.commit()
    return {"message": "Indice supprimé"}

@router.get("/verifier/{famille}/{annee}")
def verifier_indices(
    famille: str,
    annee: int,
    db: Session = Depends(get_db)
):
    """Vérifie que les indices nécessaires sont disponibles pour une famille et une année."""
    from app.services.revision_service import verifier_indices_disponibles
    result = verifier_indices_disponibles(db, famille.upper(), annee)
    return result
