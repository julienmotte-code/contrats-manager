"""
Routes API — Commandes (devis acceptés Karlia)
GET  /api/commandes/sync              → Synchronise les devis depuis Karlia
GET  /api/commandes/stats             → Statistiques
GET  /api/commandes/nouvelles         → Liste des nouvelles commandes
GET  /api/commandes/a-planifier       → Liste des commandes à planifier
GET  /api/commandes/planifiees        → Liste des commandes planifiées
GET  /api/commandes/a-commander       → Liste des commandes à traiter
GET  /api/commandes/contrats-a-creer  → Liste des commandes nécessitant un contrat
GET  /api/commandes/{id}              → Détail d'une commande
POST /api/commandes/{id}/valider      → Valider une commande (choix traitement)
POST /api/commandes/{id}/planifier    → Planifier une commande
POST /api/commandes/{id}/terminer     → Marquer comme terminée
GET  /api/commandes/{id}/pdf          → Télécharger le PDF du devis
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from typing import Optional, List
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
import io
import base64
import logging

from app.core.database import get_db
from app.services.karlia_service import karlia
from app.models.models import Commande, CommandeLigne, Prestation, Contrat
from app.services.karlia_devis_service import karlia_devis_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schémas ──────────────────────────────────────────────────────────────────

class CommandeLigneResponse(BaseModel):
    id: int
    commande_id: int
    karlia_product_id: Optional[str] = None
    designation: Optional[str] = None
    description: Optional[str] = None
    quantite: Optional[Decimal] = None
    unite: Optional[str] = None
    prix_unitaire_ht: Optional[Decimal] = None
    taux_tva: Optional[Decimal] = None
    montant_ht: Optional[Decimal] = None
    montant_tva: Optional[Decimal] = None
    montant_ttc: Optional[Decimal] = None
    ordre: Optional[int] = None

    class Config:
        from_attributes = True


class CommandeResponse(BaseModel):
    id: int
    karlia_document_id: int
    karlia_customer_id: Optional[int] = None
    karlia_opportunity_id: Optional[int] = None
    reference_devis: Optional[str] = None
    client_nom: Optional[str] = None
    client_email: Optional[str] = None
    client_telephone: Optional[str] = None
    client_adresse: Optional[str] = None
    client_siret: Optional[str] = None
    montant_ht: Optional[Decimal] = None
    montant_tva: Optional[Decimal] = None
    montant_ttc: Optional[Decimal] = None
    date_devis: Optional[date] = None
    date_acceptation: Optional[date] = None
    statut: str
    type_traitement: Optional[str] = None
    necessite_contrat: bool = False
    date_planifiee: Optional[date] = None
    intervenant_id: Optional[int] = None
    intervenant_nom: Optional[str] = None
    notes_planification: Optional[str] = None
    contrat_id: Optional[str] = None
    pdf_disponible: bool = False
    pdf_url: Optional[str] = None
    pdf_devis_nom: Optional[str] = None
    nb_prestations: int = 0
    nb_prestations_attribuees: int = 0
    nb_prestations_planifiees: int = 0
    formateur_id: Optional[int] = None
    formateur_nom: Optional[str] = None
    date_import: Optional[datetime] = None
    date_validation: Optional[datetime] = None
    lignes: List[CommandeLigneResponse] = []

    class Config:
        from_attributes = True


class CommandeListResponse(BaseModel):
    items: List[CommandeResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CommandeStats(BaseModel):
    nouvelles: int = 0
    a_planifier: int = 0
    planifiees: int = 0

    contrats_a_creer: int = 0
    total: int = 0


class SyncDevisResult(BaseModel):
    success: bool
    nouveaux_devis: int = 0
    devis_mis_a_jour: int = 0
    devis_ignores: int = 0
    opportunites_marquees: int = 0
    erreurs: List[str] = []
    message: str = ""


class CommandeValidation(BaseModel):
    type_traitement: str  # 'a_planifier' ou 'sans_planification'
    necessite_contrat: bool = False


class CommandePlanification(BaseModel):
    date_planifiee: date
    intervenant_id: Optional[int] = None
    intervenant_nom: Optional[str] = None
    notes_planification: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _commande_to_response(commande: Commande) -> CommandeResponse:
    # Compter les prestations
    prestations = commande.prestations if hasattr(commande, 'prestations') and commande.prestations else []
    nb_prestations = len(prestations)
    nb_attribuees = sum(1 for p in prestations if p.formateur_id is not None)
    nb_planifiees = sum(1 for p in prestations if p.statut == 'planifiee' or p.statut == 'realisee')
    
    return CommandeResponse(
        id=commande.id,
        karlia_document_id=commande.karlia_document_id,
        karlia_customer_id=commande.karlia_customer_id,
        reference_devis=commande.reference_devis,
        client_nom=commande.client_nom,
        client_email=commande.client_email,
        client_telephone=commande.client_telephone,
        client_adresse=commande.client_adresse,
        client_siret=commande.client_siret,
        montant_ht=commande.montant_ht,
        montant_tva=commande.montant_tva,
        montant_ttc=commande.montant_ttc,
        date_devis=commande.date_devis,
        date_acceptation=commande.date_acceptation,
        statut=commande.statut,
        type_traitement=commande.type_traitement,
        necessite_contrat=commande.necessite_contrat or False,
        date_planifiee=commande.date_planifiee,
        intervenant_id=commande.intervenant_id,
        intervenant_nom=commande.intervenant_nom,
        notes_planification=commande.notes_planification,
        contrat_id=str(commande.contrat_id) if commande.contrat_id else None,
        pdf_disponible=bool(commande.pdf_url or commande.pdf_devis),
        pdf_url=commande.pdf_url,
        pdf_devis_nom=commande.pdf_devis_nom,
        nb_prestations=nb_prestations,
        nb_prestations_attribuees=nb_attribuees,
        nb_prestations_planifiees=nb_planifiees,
        formateur_id=commande.formateur_id,
        formateur_nom=f"{commande.formateur.prenom or ''} {commande.formateur.nom}".strip() if commande.formateur else None,
        date_import=commande.date_import,
        date_validation=commande.date_validation,
        lignes=[CommandeLigneResponse.model_validate(l) for l in commande.lignes]
    )


def _get_commandes_by_statut(db: Session, statut: str, page: int, page_size: int, search: Optional[str]) -> CommandeListResponse:
    query = db.query(Commande).options(joinedload(Commande.lignes), joinedload(Commande.prestations), joinedload(Commande.formateur)).filter(Commande.statut == statut)
    if search:
        query = query.filter(or_(
            Commande.client_nom.ilike(f"%{search}%"),
            Commande.reference_devis.ilike(f"%{search}%")
        ))
    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    commandes = query.order_by(Commande.date_import.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return CommandeListResponse(
        items=[_commande_to_response(c) for c in commandes],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/sync", response_model=SyncDevisResult)
async def sync_devis_karlia(force_full: bool = Query(False), db: Session = Depends(get_db)):
    """Synchronise les devis acceptés depuis Karlia."""
    try:
        result = await karlia_devis_service.sync_devis_acceptes(db, force_full=force_full)
        return SyncDevisResult(**result)
    except Exception as e:
        logger.error(f"Erreur sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=CommandeStats)
async def get_commandes_stats(db: Session = Depends(get_db)):
    """Retourne les statistiques des commandes."""
    return CommandeStats(
        nouvelles=db.query(Commande).filter(Commande.statut == "nouvelle").count(),
        a_planifier=db.query(Commande).filter(Commande.statut == "a_planifier").count(),
        planifiees=db.query(Commande).filter(Commande.statut == "planifiee").count(),
        contrats_a_creer=db.query(Commande).filter(
            Commande.necessite_contrat == True,
            Commande.contrat_id == None
        ).count(),
        total=db.query(Commande).count()
    )


@router.get("/nouvelles", response_model=CommandeListResponse)
async def get_nouvelles_commandes(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Liste des nouvelles commandes à traiter."""
    return _get_commandes_by_statut(db, "nouvelle", page, page_size, search)


@router.get("/a-planifier", response_model=CommandeListResponse)
async def get_commandes_a_planifier(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Liste des commandes à planifier."""
    return _get_commandes_by_statut(db, "a_planifier", page, page_size, search)


@router.get("/planifiees", response_model=CommandeListResponse)
async def get_commandes_planifiees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Liste des commandes planifiées."""
    return _get_commandes_by_statut(db, "planifiee", page, page_size, search)


@router.get("/terminees", response_model=CommandeListResponse)
async def get_commandes_terminees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Liste des commandes terminées (prestations réalisées, à facturer)."""
    return _get_commandes_by_statut(db, "deployee", page, page_size, search)




@router.get("/contrats-a-creer", response_model=CommandeListResponse)
async def get_contrats_a_creer(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Liste des commandes nécessitant la création d'un contrat/avenant."""
    query = db.query(Commande).filter(
        Commande.necessite_contrat == True,
        Commande.contrat_id == None
    )
    if search:
        query = query.filter(or_(
            Commande.client_nom.ilike(f"%{search}%"),
            Commande.reference_devis.ilike(f"%{search}%")
        ))
    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    commandes = query.order_by(Commande.date_import.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return CommandeListResponse(
        items=[_commande_to_response(c) for c in commandes],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{commande_id}", response_model=CommandeResponse)
async def get_commande(commande_id: int, db: Session = Depends(get_db)):
    """Récupère les détails d'une commande."""
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    return _commande_to_response(commande)


@router.post("/{commande_id}/valider", response_model=CommandeResponse)
async def valider_commande(
    commande_id: int,
    validation: CommandeValidation,
    db: Session = Depends(get_db)
):
    """Valide une commande avec le choix de traitement."""
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    if commande.statut != "nouvelle":
        raise HTTPException(status_code=400, detail="Cette commande a déjà été validée")
    if validation.type_traitement not in ["a_planifier", "sans_planification"]:
        raise HTTPException(status_code=400, detail="type_traitement invalide")
    
    commande.type_traitement = validation.type_traitement
    commande.necessite_contrat = validation.necessite_contrat
    commande.date_validation = datetime.utcnow()
    commande.statut = "a_planifier" if validation.type_traitement == "a_planifier" else "deployee"
    
    db.commit()
    db.refresh(commande)
    return _commande_to_response(commande)


@router.post("/{commande_id}/planifier", response_model=CommandeResponse)
async def planifier_commande(
    commande_id: int,
    planification: CommandePlanification,
    db: Session = Depends(get_db)
):
    """Planifie une commande (date et intervenant)."""
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    if commande.statut != "a_planifier":
        raise HTTPException(status_code=400, detail="Seules les commandes 'à planifier' peuvent être planifiées")
    
    commande.date_planifiee = planification.date_planifiee
    commande.intervenant_id = planification.intervenant_id
    commande.intervenant_nom = planification.intervenant_nom
    commande.notes_planification = planification.notes_planification
    commande.statut = "planifiee"
    commande.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(commande)
    return _commande_to_response(commande)


@router.post("/{commande_id}/terminer", response_model=CommandeResponse)
async def terminer_commande(commande_id: int, db: Session = Depends(get_db)):
    """Marque une commande comme terminée."""
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    
    commande.statut = "terminee"
    commande.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(commande)
    return _commande_to_response(commande)


@router.post("/{commande_id}/lier-contrat/{contrat_id}", response_model=CommandeResponse)
async def lier_contrat_commande(commande_id: int, contrat_id: str, db: Session = Depends(get_db)):
    """Lie un contrat créé à une commande."""
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    
    contrat = db.query(Contrat).filter(Contrat.id == contrat_id).first()
    if not contrat:
        raise HTTPException(status_code=404, detail="Contrat non trouvé")
    
    commande.contrat_id = contrat_id
    commande.updated_at = datetime.utcnow()
    
    db.commit()
    db.refresh(commande)
    return _commande_to_response(commande)


@router.get("/{commande_id}/pdf")
async def get_commande_pdf(commande_id: int, db: Session = Depends(get_db)):
    """Redirige vers le PDF du devis sur Karlia."""
    from fastapi.responses import RedirectResponse
    
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    
    # Utiliser l'URL directe si disponible
    if commande.pdf_url:
        return RedirectResponse(url=commande.pdf_url)
    
    raise HTTPException(status_code=404, detail="PDF non disponible")
    
    filename = commande.pdf_devis_nom or f"devis_{commande.reference_devis or commande.id}.pdf"
    
    # Décoder le base64 si nécessaire
    pdf_content = commande.pdf_devis
    if isinstance(pdf_content, bytes):
        pdf_content = base64.b64decode(pdf_content.decode("utf-8"))
    elif isinstance(pdf_content, str):
        pdf_content = base64.b64decode(pdf_content)
    
    return StreamingResponse(
        io.BytesIO(pdf_content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.post("/{commande_id}/facturer")
async def facturer_commande(
    commande_id: int,
    db: Session = Depends(get_db)
):
    """Émet une facture Karlia pour une commande terminée."""
    commande = db.query(Commande).options(
        joinedload(Commande.lignes)
    ).filter(Commande.id == commande_id).first()
    
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    
    if commande.statut != "deployee":
        raise HTTPException(status_code=400, detail="Seules les commandes terminées peuvent être facturées")
    
    if not commande.karlia_customer_id:
        raise HTTPException(status_code=400, detail="Client Karlia non renseigné sur cette commande")
    
    # Préparer les lignes pour Karlia
    lignes_karlia = []
    for ligne in commande.lignes:
        lignes_karlia.append({
            "id_product": ligne.karlia_product_id,
            "quantity": float(ligne.quantite or 1),
            "unit_price": float(ligne.prix_unitaire_ht or 0),
            "vat_rate": float(ligne.taux_tva or 20),
            "description": ligne.designation or ""
        })
    
    if not lignes_karlia:
        raise HTTPException(status_code=400, detail="Aucune ligne à facturer")
    
    try:
        # Créer la facture dans Karlia
        result = await karlia.creer_facture(
            client_karlia_id=str(commande.karlia_customer_id),
            lignes=lignes_karlia,
            reference_contrat=commande.reference_devis or f"CMD-{commande.id}",
            date_echeance=date.today(),
            montant_ht=float(commande.montant_ht or 0),
            description=f"Facturation prestation - {commande.reference_devis}"
        )
        
        # Mettre à jour la commande
        commande.statut = "facturee"
        commande.facture_karlia_id = str(result.get("id", ""))
        commande.facture_karlia_ref = result.get("reference", "")
        commande.updated_at = datetime.utcnow()
        db.commit()
        
        return {
            "success": True,
            "message": f"Facture {result.get('reference', '')} émise avec succès",
            "karlia_doc_id": result.get("id"),
            "karlia_doc_ref": result.get("reference")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur Karlia: {str(e)}")
