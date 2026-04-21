"""
API de gestion des prestations.
"""
from typing import List, Optional
from datetime import datetime, date, time
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.core.database import get_db
from app.models.models import Prestation, Commande, CommandeLigne, Formateur, Utilisateur
from app.api.auth import get_current_user
from app.services.google_calendar_service import google_calendar_service

router = APIRouter(tags=["prestations"])


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
    agenda_formateur_id: Optional[int] = None
    heure_debut: Optional[time] = None
    heure_fin: Optional[time] = None
    lieu: Optional[str] = None
    notes: Optional[str] = None

class PrestationResponse(BaseModel):
    id: int
    commande_id: int
    commande_ligne_id: Optional[int]
    formateur_id: Optional[int]
    agenda_formateur_id: Optional[int] = None
    google_calendar_id: Optional[str] = None
    google_sync_status: Optional[str] = None
    google_sync_error: Optional[str] = None
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
        agenda_formateur_id=prestation.agenda_formateur_id,
        google_calendar_id=prestation.google_calendar_id,
        google_sync_status=prestation.google_sync_status,
        google_sync_error=prestation.google_sync_error,
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
    
    existing = db.query(Prestation).filter(Prestation.commande_id == commande_id).count()
    if existing > 0:
        raise HTTPException(status_code=400, detail=f"Des prestations existent déjà pour cette commande ({existing})")
    
    lignes = db.query(CommandeLigne).filter(CommandeLigne.commande_id == commande_id).all()
    
    created = []
    for ligne in lignes:
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
    db: Session = Depends(get_db),
    current_user: Utilisateur = Depends(get_current_user)
):
    """Planifie une prestation (définit la date)."""
    prestation = db.query(Prestation).filter(Prestation.id == prestation_id).first()
    if not prestation:
        raise HTTPException(status_code=404, detail="Prestation non trouvée")
    
    agenda_cible_id = data.agenda_formateur_id or prestation.formateur_id
    if not agenda_cible_id:
        raise HTTPException(status_code=400, detail="Aucun agenda cible défini")

    agenda_cible = db.query(Formateur).filter(
        Formateur.id == agenda_cible_id,
        Formateur.actif == True
    ).first()
    if not agenda_cible:
        raise HTTPException(status_code=400, detail="Agenda cible introuvable ou inactif")

    if current_user.role == "FORMATEUR":
        if not current_user.formateur_id or prestation.formateur_id != current_user.formateur_id:
            raise HTTPException(status_code=403, detail="Vous ne pouvez planifier que vos prestations")
        if agenda_cible_id != current_user.formateur_id:
            raise HTTPException(status_code=403, detail="Vous ne pouvez planifier que sur votre propre agenda")

    elif current_user.role == "TECHNICIEN":
        if not current_user.formateur_id or prestation.formateur_id != current_user.formateur_id:
            raise HTTPException(status_code=403, detail="Vous ne pouvez planifier que vos prestations")
        # Le technicien peut planifier sur son agenda ou sur un agenda formateur actif

    elif current_user.role not in ("ADMIN", "GESTIONNAIRE"):
        raise HTTPException(status_code=403, detail="Droits insuffisants pour planifier cette prestation")

    prestation.date_planifiee = data.date_planifiee
    prestation.agenda_formateur_id = data.agenda_formateur_id or prestation.formateur_id
    prestation.heure_debut = data.heure_debut
    prestation.heure_fin = data.heure_fin
    prestation.lieu = data.lieu or prestation.lieu
    prestation.notes = data.notes or prestation.notes
    prestation.statut = 'planifiee'
    prestation.updated_at = datetime.utcnow()

    agenda_email = agenda_cible.email_google or agenda_cible.email
    google_result = google_calendar_service.create_or_update_event(
        prestation_id=prestation.id,
        title=prestation.designation,
        agenda_email=agenda_email,
        date_planifiee=str(data.date_planifiee),
        heure_debut=str(data.heure_debut) if data.heure_debut else None,
        heure_fin=str(data.heure_fin) if data.heure_fin else None,
        lieu=prestation.lieu,
        notes=prestation.notes,
        existing_event_id=prestation.google_event_id,
    )

    prestation.google_calendar_id = google_result.get("calendar_id")
    prestation.google_event_id = google_result.get("event_id")
    prestation.google_sync_status = google_result.get("status")
    prestation.google_sync_error = google_result.get("error")
    if google_result.get("success"):
        prestation.google_synced_at = datetime.utcnow()
    
    db.commit()
    db.refresh(prestation)
    
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
    
    prestations = db.query(Prestation).filter(Prestation.commande_id == commande_id).all()
    for p in prestations:
        p.formateur_id = formateur_id
        p.updated_at = datetime.utcnow()
    
    commande.formateur_id = formateur_id
    commande.updated_at = datetime.utcnow()
    
    db.commit()
    
    return {
        "success": True,
        "message": f"{len(prestations)} prestation(s) réattribuée(s) à {formateur.prenom or ''} {formateur.nom}".strip(),
        "nb_prestations": len(prestations)
    }
