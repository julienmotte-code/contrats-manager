"""
API de gestion des prestations.
"""
from typing import List, Optional
from datetime import datetime, date, time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel

from app.core.database import get_db
from app.models.models import Prestation, Commande, CommandeLigne, Formateur

router = APIRouter(tags=["prestations"])


# ══════════════════════════════════════════════════════════════════════════════
# SCHÉMAS
# ══════════════════════════════════════════════════════════════════════════════

class PrestationCreate(BaseModel):
    commande_id: int
    commande_ligne_id: Optional[int] = None
    formateur_id: Optional[int] = None
    designation: str
    description: Optional[str] = None
    duree_jours: Optional[float] = 1
    date_prevue: Optional[date] = None
    lieu: Optional[str] = None

class PrestationUpdate(BaseModel):
    formateur_id: Optional[int] = None
    designation: Optional[str] = None
    description: Optional[str] = None
    duree_jours: Optional[float] = None
    date_prevue: Optional[date] = None
    date_planifiee: Optional[date] = None
    heure_debut: Optional[time] = None
    heure_fin: Optional[time] = None
    lieu: Optional[str] = None
    statut: Optional[str] = None
    notes: Optional[str] = None

class PrestationPlanifier(BaseModel):
    date_planifiee: date
    heure_debut: Optional[time] = None
    heure_fin: Optional[time] = None
    lieu: Optional[str] = None
    notes: Optional[str] = None

class PrestationResponse(BaseModel):
    id: int
    commande_id: int
    commande_ligne_id: Optional[int]
    formateur_id: Optional[int]
    formateur_nom: Optional[str] = None
    designation: str
    description: Optional[str]
    duree_jours: float
    date_prevue: Optional[date]
    date_planifiee: Optional[date]
    heure_debut: Optional[time]
    heure_fin: Optional[time]
    lieu: Optional[str]
    google_event_id: Optional[str]
    statut: str
    notes: Optional[str]
    client_nom: Optional[str] = None
    reference_devis: Optional[str] = None
    
    class Config:
        from_attributes = True

class PrestationListResponse(BaseModel):
    prestations: List[PrestationResponse]
    total: int
    a_planifier: int
    planifiees: int
    realisees: int


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _prestation_to_response(prestation: Prestation, db: Session) -> PrestationResponse:
    formateur_nom = None
    if prestation.formateur_id:
        formateur = db.query(Formateur).filter(Formateur.id == prestation.formateur_id).first()
        if formateur:
            formateur_nom = f"{formateur.prenom or ''} {formateur.nom}".strip()
    
    commande = db.query(Commande).filter(Commande.id == prestation.commande_id).first()
    
    return PrestationResponse(
        id=prestation.id,
        commande_id=prestation.commande_id,
        commande_ligne_id=prestation.commande_ligne_id,
        formateur_id=prestation.formateur_id,
        formateur_nom=formateur_nom,
        designation=prestation.designation,
        description=prestation.description,
        duree_jours=float(prestation.duree_jours or 1),
        date_prevue=prestation.date_prevue,
        date_planifiee=prestation.date_planifiee,
        heure_debut=prestation.heure_debut,
        heure_fin=prestation.heure_fin,
        lieu=prestation.lieu,
        google_event_id=prestation.google_event_id,
        statut=prestation.statut,
        notes=prestation.notes,
        client_nom=commande.client_nom if commande else None,
        reference_devis=commande.reference_devis if commande else None
    )


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("", response_model=PrestationListResponse)
async def list_prestations(
    formateur_id: Optional[int] = None,
    commande_id: Optional[int] = None,
    statut: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Liste les prestations avec filtres optionnels."""
    query = db.query(Prestation)
    
    if formateur_id:
        query = query.filter(Prestation.formateur_id == formateur_id)
    if commande_id:
        query = query.filter(Prestation.commande_id == commande_id)
    if statut:
        query = query.filter(Prestation.statut == statut)
    
    prestations = query.order_by(Prestation.date_planifiee.asc().nullsfirst(), Prestation.id).all()
    
    result = [_prestation_to_response(p, db) for p in prestations]
    
    a_planifier = sum(1 for p in prestations if p.statut == 'a_planifier')
    planifiees = sum(1 for p in prestations if p.statut == 'planifiee')
    realisees = sum(1 for p in prestations if p.statut == 'realisee')
    
    return PrestationListResponse(
        prestations=result,
        total=len(result),
        a_planifier=a_planifier,
        planifiees=planifiees,
        realisees=realisees
    )


@router.get("/formateur/{formateur_id}", response_model=PrestationListResponse)
async def list_prestations_formateur(
    formateur_id: int,
    statut: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Liste les prestations d'un formateur."""
    formateur = db.query(Formateur).filter(Formateur.id == formateur_id).first()
    if not formateur:
        raise HTTPException(status_code=404, detail="Formateur non trouvé")
    
    query = db.query(Prestation).filter(Prestation.formateur_id == formateur_id)
    
    if statut:
        query = query.filter(Prestation.statut == statut)
    
    prestations = query.order_by(Prestation.date_planifiee.asc().nullsfirst(), Prestation.id).all()
    
    result = [_prestation_to_response(p, db) for p in prestations]
    
    a_planifier = sum(1 for p in prestations if p.statut == 'a_planifier')
    planifiees = sum(1 for p in prestations if p.statut == 'planifiee')
    realisees = sum(1 for p in prestations if p.statut == 'realisee')
    
    return PrestationListResponse(
        prestations=result,
        total=len(result),
        a_planifier=a_planifier,
        planifiees=planifiees,
        realisees=realisees
    )


@router.post("", response_model=PrestationResponse)
async def create_prestation(
    data: PrestationCreate,
    db: Session = Depends(get_db)
):
    """Crée une nouvelle prestation."""
    commande = db.query(Commande).filter(Commande.id == data.commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    
    prestation = Prestation(
        commande_id=data.commande_id,
        commande_ligne_id=data.commande_ligne_id,
        formateur_id=data.formateur_id,
        designation=data.designation,
        description=data.description,
        duree_jours=data.duree_jours or 1,
        date_prevue=data.date_prevue,
        lieu=data.lieu,
        statut='a_planifier'
    )
    db.add(prestation)
    db.commit()
    db.refresh(prestation)
    
    return _prestation_to_response(prestation, db)


@router.post("/from-commande/{commande_id}")
async def create_prestations_from_commande(
    commande_id: int,
    formateur_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """Crée automatiquement les prestations depuis les lignes de commande."""
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    
    # Vérifier s'il existe déjà des prestations
    existing = db.query(Prestation).filter(Prestation.commande_id == commande_id).count()
    if existing > 0:
        raise HTTPException(status_code=400, detail=f"Des prestations existent déjà pour cette commande ({existing})")
    
    lignes = db.query(CommandeLigne).filter(CommandeLigne.commande_id == commande_id).all()
    
    created = []
    for ligne in lignes:
        # Créer une prestation par quantité
        quantite = int(ligne.quantite or 1)
        for i in range(quantite):
            prestation = Prestation(
                commande_id=commande_id,
                commande_ligne_id=ligne.id,
                formateur_id=formateur_id,
                designation=ligne.designation or f"Prestation {i+1}",
                description=ligne.description,
                duree_jours=1,
                statut='a_planifier'
            )
            db.add(prestation)
            created.append(prestation)
    
    # Mettre à jour le statut de la commande si formateur assigné
    if formateur_id:
        commande.formateur_id = formateur_id
        commande.statut = 'a_planifier'
    
    db.commit()
    
    return {
        "success": True,
        "message": f"{len(created)} prestations créées",
        "nb_prestations": len(created)
    }


@router.get("/{prestation_id}", response_model=PrestationResponse)
async def get_prestation(
    prestation_id: int,
    db: Session = Depends(get_db)
):
    """Récupère une prestation par son ID."""
    prestation = db.query(Prestation).filter(Prestation.id == prestation_id).first()
    if not prestation:
        raise HTTPException(status_code=404, detail="Prestation non trouvée")
    
    return _prestation_to_response(prestation, db)


@router.put("/{prestation_id}", response_model=PrestationResponse)
async def update_prestation(
    prestation_id: int,
    data: PrestationUpdate,
    db: Session = Depends(get_db)
):
    """Met à jour une prestation."""
    prestation = db.query(Prestation).filter(Prestation.id == prestation_id).first()
    if not prestation:
        raise HTTPException(status_code=404, detail="Prestation non trouvée")
    
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(prestation, field, value)
    
    prestation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prestation)
    
    return _prestation_to_response(prestation, db)


@router.post("/{prestation_id}/planifier", response_model=PrestationResponse)
async def planifier_prestation(
    prestation_id: int,
    data: PrestationPlanifier,
    db: Session = Depends(get_db)
):
    """Planifie une prestation (définit la date)."""
    prestation = db.query(Prestation).filter(Prestation.id == prestation_id).first()
    if not prestation:
        raise HTTPException(status_code=404, detail="Prestation non trouvée")
    
    prestation.date_planifiee = data.date_planifiee
    prestation.heure_debut = data.heure_debut
    prestation.heure_fin = data.heure_fin
    prestation.lieu = data.lieu or prestation.lieu
    prestation.notes = data.notes or prestation.notes
    prestation.statut = 'planifiee'
    prestation.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(prestation)
    
    # Vérifier si toutes les prestations de la commande sont planifiées
    commande = db.query(Commande).filter(Commande.id == prestation.commande_id).first()
    if commande:
        all_prestations = db.query(Prestation).filter(Prestation.commande_id == commande.id).all()
        if all(p.statut in ['planifiee', 'realisee'] for p in all_prestations):
            commande.statut = 'planifiee'
            db.commit()
    
    return _prestation_to_response(prestation, db)


@router.post("/{prestation_id}/realiser", response_model=PrestationResponse)
async def realiser_prestation(
    prestation_id: int,
    db: Session = Depends(get_db)
):
    """Marque une prestation comme réalisée."""
    prestation = db.query(Prestation).filter(Prestation.id == prestation_id).first()
    if not prestation:
        raise HTTPException(status_code=404, detail="Prestation non trouvée")
    
    prestation.statut = 'realisee'
    prestation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prestation)
    
    # Vérifier si toutes les prestations sont réalisées
    commande = db.query(Commande).filter(Commande.id == prestation.commande_id).first()
    if commande:
        all_prestations = db.query(Prestation).filter(Prestation.commande_id == commande.id).all()
        if all(p.statut == 'realisee' for p in all_prestations):
            commande.statut = 'deployee'
            db.commit()
    
    return _prestation_to_response(prestation, db)


@router.delete("/{prestation_id}")
async def delete_prestation(
    prestation_id: int,
    db: Session = Depends(get_db)
):
    """Supprime une prestation."""
    prestation = db.query(Prestation).filter(Prestation.id == prestation_id).first()
    if not prestation:
        raise HTTPException(status_code=404, detail="Prestation non trouvée")
    
    db.delete(prestation)
    db.commit()
    
    return {"success": True, "message": "Prestation supprimée"}


@router.post("/reattribuer-commande/{commande_id}")
async def reattribuer_prestations_commande(
    commande_id: int,
    formateur_id: int,
    db: Session = Depends(get_db)
):
    """Réattribue toutes les prestations d'une commande à un autre formateur."""
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    
    formateur = db.query(Formateur).filter(Formateur.id == formateur_id).first()
    if not formateur:
        raise HTTPException(status_code=404, detail="Formateur non trouvé")
    
    # Mettre à jour toutes les prestations de cette commande
    prestations = db.query(Prestation).filter(Prestation.commande_id == commande_id).all()
    for p in prestations:
        p.formateur_id = formateur_id
        p.updated_at = datetime.utcnow()
    
    # Mettre à jour la commande
    commande.formateur_id = formateur_id
    commande.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "success": True,
        "message": f"{len(prestations)} prestation(s) réattribuée(s) à {formateur.prenom or ''} {formateur.nom}".strip(),
        "nb_prestations": len(prestations)
    }
