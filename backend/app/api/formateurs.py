"""
API de gestion des formateurs.
"""
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr

from app.core.database import get_db
from app.models.models import Formateur, Commande, Prestation

router = APIRouter(tags=["formateurs"])


class FormateurCreate(BaseModel):
    nom: str
    prenom: Optional[str] = None
    email: EmailStr
    email_google: Optional[str] = None
    telephone: Optional[str] = None
    couleur: Optional[str] = '#3788d8'

class FormateurUpdate(BaseModel):
    nom: Optional[str] = None
    prenom: Optional[str] = None
    email: Optional[EmailStr] = None
    email_google: Optional[str] = None
    telephone: Optional[str] = None
    actif: Optional[bool] = None
    couleur: Optional[str] = None

class FormateurResponse(BaseModel):
    id: int
    nom: str
    prenom: Optional[str]
    email: str
    email_google: Optional[str]
    telephone: Optional[str]
    actif: bool
    couleur: str
    nb_commandes: int = 0
    nb_prestations_a_planifier: int = 0
    
    class Config:
        from_attributes = True

class FormateurListResponse(BaseModel):
    formateurs: List[FormateurResponse]
    total: int


@router.get("", response_model=FormateurListResponse)
async def list_formateurs(
    actif_only: bool = True,
    db: Session = Depends(get_db)
):
    """Liste tous les formateurs."""
    query = db.query(Formateur)
    if actif_only:
        query = query.filter(Formateur.actif == True)
    formateurs = query.order_by(Formateur.nom).all()
    
    result = []
    for f in formateurs:
        nb_commandes = db.query(Commande).filter(Commande.formateur_id == f.id).count()
        nb_prestations = db.query(Prestation).filter(
            Prestation.formateur_id == f.id,
            Prestation.statut == 'a_planifier'
        ).count()
        result.append(FormateurResponse(
            id=f.id,
            nom=f.nom,
            prenom=f.prenom,
            email=f.email,
            email_google=f.email_google,
            telephone=f.telephone,
            actif=f.actif,
            couleur=f.couleur,
            nb_commandes=nb_commandes,
            nb_prestations_a_planifier=nb_prestations
        ))
    
    return FormateurListResponse(formateurs=result, total=len(result))


@router.post("", response_model=FormateurResponse)
async def create_formateur(
    data: FormateurCreate,
    db: Session = Depends(get_db)
):
    """Crée un nouveau formateur."""
    existing = db.query(Formateur).filter(Formateur.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Un formateur avec cet email existe déjà")
    
    formateur = Formateur(
        nom=data.nom,
        prenom=data.prenom,
        email=data.email,
        email_google=data.email_google or data.email,
        telephone=data.telephone,
        couleur=data.couleur or '#3788d8'
    )
    db.add(formateur)
    db.commit()
    db.refresh(formateur)
    
    return FormateurResponse(
        id=formateur.id,
        nom=formateur.nom,
        prenom=formateur.prenom,
        email=formateur.email,
        email_google=formateur.email_google,
        telephone=formateur.telephone,
        actif=formateur.actif,
        couleur=formateur.couleur,
        nb_commandes=0,
        nb_prestations_a_planifier=0
    )


@router.get("/{formateur_id}", response_model=FormateurResponse)
async def get_formateur(
    formateur_id: int,
    db: Session = Depends(get_db)
):
    """Récupère un formateur par son ID."""
    formateur = db.query(Formateur).filter(Formateur.id == formateur_id).first()
    if not formateur:
        raise HTTPException(status_code=404, detail="Formateur non trouvé")
    
    nb_commandes = db.query(Commande).filter(Commande.formateur_id == formateur.id).count()
    nb_prestations = db.query(Prestation).filter(
        Prestation.formateur_id == formateur.id,
        Prestation.statut == 'a_planifier'
    ).count()
    
    return FormateurResponse(
        id=formateur.id,
        nom=formateur.nom,
        prenom=formateur.prenom,
        email=formateur.email,
        email_google=formateur.email_google,
        telephone=formateur.telephone,
        actif=formateur.actif,
        couleur=formateur.couleur,
        nb_commandes=nb_commandes,
        nb_prestations_a_planifier=nb_prestations
    )


@router.put("/{formateur_id}", response_model=FormateurResponse)
async def update_formateur(
    formateur_id: int,
    data: FormateurUpdate,
    db: Session = Depends(get_db)
):
    """Met à jour un formateur."""
    formateur = db.query(Formateur).filter(Formateur.id == formateur_id).first()
    if not formateur:
        raise HTTPException(status_code=404, detail="Formateur non trouvé")
    
    if data.nom is not None:
        formateur.nom = data.nom
    if data.prenom is not None:
        formateur.prenom = data.prenom
    if data.email is not None:
        existing = db.query(Formateur).filter(
            Formateur.email == data.email,
            Formateur.id != formateur_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="Cet email est déjà utilisé")
        formateur.email = data.email
    if data.email_google is not None:
        formateur.email_google = data.email_google
    if data.telephone is not None:
        formateur.telephone = data.telephone
    if data.actif is not None:
        formateur.actif = data.actif
    if data.couleur is not None:
        formateur.couleur = data.couleur
    
    formateur.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(formateur)
    
    nb_commandes = db.query(Commande).filter(Commande.formateur_id == formateur.id).count()
    nb_prestations = db.query(Prestation).filter(
        Prestation.formateur_id == formateur.id,
        Prestation.statut == 'a_planifier'
    ).count()
    
    return FormateurResponse(
        id=formateur.id,
        nom=formateur.nom,
        prenom=formateur.prenom,
        email=formateur.email,
        email_google=formateur.email_google,
        telephone=formateur.telephone,
        actif=formateur.actif,
        couleur=formateur.couleur,
        nb_commandes=nb_commandes,
        nb_prestations_a_planifier=nb_prestations
    )


@router.delete("/{formateur_id}")
async def delete_formateur(
    formateur_id: int,
    db: Session = Depends(get_db)
):
    """Désactive un formateur (soft delete)."""
    formateur = db.query(Formateur).filter(Formateur.id == formateur_id).first()
    if not formateur:
        raise HTTPException(status_code=404, detail="Formateur non trouvé")
    
    formateur.actif = False
    formateur.updated_at = datetime.utcnow()
    db.commit()
    
    return {"success": True, "message": "Formateur désactivé"}
