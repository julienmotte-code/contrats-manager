"""
Routes API — Factures fournisseurs (construites depuis les BR Karlia).

Périmètre (étape 2/3) :
  - GET    /api/factures-fournisseurs/facturables    : liste les lignes
           facturables groupées par fournisseur (lecture Karlia + pointage SGI).
           Paramètre optionnel `force_refresh=true` pour bypasser le cache
           du catalogue produits (bouton "Rafraîchir" côté UI).
  - GET    /api/factures-fournisseurs                : liste les factures
           locales (filtre statut optionnel).
  - GET    /api/factures-fournisseurs/{id}           : détail d'une facture.
           Renvoie quantite_max_facturable par ligne — borne consommée par
           l'écran d'édition sans rappel /facturables.
  - POST   /api/factures-fournisseurs                : crée un brouillon.
  - PUT    /api/factures-fournisseurs/{id}           : remplace les lignes du
           brouillon, recalcule les totaux.
  - POST   /api/factures-fournisseurs/{id}/valider   : valide le brouillon
           (incrémente le pointage anti-doublon, statut → 'validee').
  - DELETE /api/factures-fournisseurs/{id}           : supprime un brouillon.

Aucune émission Karlia (POST /suppliers-documents bloqué côté Karlia, en
attente support). Toutes les routes sont protégées en ADMIN/GESTIONNAIRE
(pas de FORMATEUR/TECHNICIEN — flux compta interne).
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import require_role
from app.models.models import (
    FactureFournisseur,
    FactureFournisseurLigne,
)
from app.services.karlia_factures_fournisseurs_service import (
    KarliaBodyError,
    karlia_factures_fournisseurs_service,
)
from app.services.karlia_service import KarliaError

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Schémas Pydantic ─────────────────────────────────────────────────────────


class LigneFacturable(BaseModel):
    """Ligne du retour /facturables (proposition front)."""
    ligne_index: int
    id_product: Optional[int] = None
    designation: str
    reference: Optional[str] = None
    quantite_livree: Decimal
    quantite_deja_facturee: Decimal
    quantite_restante: Decimal
    prix_unitaire_ht: Decimal
    id_vat: Optional[str] = None


class BonReceptionFacturable(BaseModel):
    id_bl: int
    numero: Optional[str] = None
    date: Optional[str] = None
    lignes: List[LigneFacturable]


class FournisseurFacturable(BaseModel):
    id_fournisseur: int
    nom_fournisseur: Optional[str] = None
    bons_reception: List[BonReceptionFacturable]


class LigneSelectionnee(BaseModel):
    """Ligne posée par le front au moment de la création/MAJ d'un brouillon."""
    id_bl_karlia: int
    ligne_index: int
    id_product: Optional[int] = None
    designation: str = Field(..., min_length=1, max_length=500)
    reference: Optional[str] = Field(default=None, max_length=200)
    quantite: Decimal = Field(..., gt=0)
    prix_unitaire_ht: Decimal = Field(..., ge=0)
    id_vat: Optional[str] = Field(default=None, max_length=10)


class FactureCreateRequest(BaseModel):
    id_fournisseur: int
    lignes: List[LigneSelectionnee] = Field(..., min_length=1)


class FactureUpdateRequest(BaseModel):
    lignes: List[LigneSelectionnee] = Field(..., min_length=1)


class FactureLigneResponse(BaseModel):
    id: int
    id_bl_karlia: int
    ligne_index: int
    id_product_karlia: Optional[int] = None
    designation: str
    reference: Optional[str] = None
    quantite: Decimal
    prix_unitaire_ht: Decimal
    id_vat_karlia: Optional[str] = None
    total_ht: Decimal
    # Snapshot du restant facturable à la création — borne max consommée
    # par l'écran d'édition (évite un rappel /facturables ~10 s).
    # NULL pour les lignes créées avant migration 0004.
    quantite_max_facturable: Optional[Decimal] = None

    class Config:
        from_attributes = True


class FactureResponse(BaseModel):
    id: int
    id_fournisseur_karlia: int
    nom_fournisseur: Optional[str] = None
    statut: str
    date_facture: Optional[date] = None
    reference: Optional[str] = None
    total_ht: Decimal
    total_tva: Decimal
    total_ttc: Decimal
    id_suppliers_document_karlia: Optional[int] = None
    statut_emission_karlia: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    lignes: List[FactureLigneResponse] = []

    class Config:
        from_attributes = True


class FactureListItem(BaseModel):
    id: int
    id_fournisseur_karlia: int
    nom_fournisseur: Optional[str] = None
    statut: str
    date_facture: Optional[date] = None
    reference: Optional[str] = None
    total_ht: Decimal
    total_tva: Decimal
    total_ttc: Decimal
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    nb_lignes: int

    class Config:
        from_attributes = True


# ── Helpers ──────────────────────────────────────────────────────────────────


def _to_response(facture: FactureFournisseur) -> FactureResponse:
    return FactureResponse(
        id=facture.id,
        id_fournisseur_karlia=facture.id_fournisseur_karlia,
        nom_fournisseur=facture.nom_fournisseur,
        statut=facture.statut,
        date_facture=facture.date_facture,
        reference=facture.reference,
        total_ht=facture.total_ht,
        total_tva=facture.total_tva,
        total_ttc=facture.total_ttc,
        id_suppliers_document_karlia=facture.id_suppliers_document_karlia,
        statut_emission_karlia=facture.statut_emission_karlia,
        created_at=facture.created_at,
        updated_at=facture.updated_at,
        lignes=[FactureLigneResponse.model_validate(l) for l in facture.lignes],
    )


def _karlia_to_http(exc: Exception) -> HTTPException:
    """Traduit une erreur Karlia (corps invalide ou HTTP) en 502."""
    if isinstance(exc, KarliaBodyError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Karlia a renvoyé une erreur sur {exc.endpoint} : {exc.message}",
        )
    if isinstance(exc, KarliaError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erreur Karlia : {exc.message}",
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=f"Erreur Karlia inattendue : {exc}",
    )


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/facturables", response_model=List[FournisseurFacturable])
async def lister_facturables(
    id_fournisseur: Optional[int] = Query(
        default=None,
        description="Filtre fournisseur (id_customer_supplier Karlia)",
    ),
    force_refresh: bool = Query(
        default=False,
        description="Bypass le cache mémoire du catalogue produits Karlia. "
                    "Utilisé par le bouton 'Rafraîchir' côté UI quand l'utilisateur "
                    "sait que Karlia a changé (création produit, etc.).",
    ),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Retourne les lignes facturables (BR Karlia non encore intégralement
    consommés par une facture validée locale), groupées par fournisseur.

    Les filtres appliqués sont décrits dans le service. Les erreurs Karlia
    (corps invalide, "API not available", 4xx/5xx) remontent en HTTP 502.
    """
    try:
        groupes = await karlia_factures_fournisseurs_service.lister_bons_reception_facturables(
            db,
            id_fournisseur=id_fournisseur,
            force_refresh=force_refresh,
        )
    except (KarliaBodyError, KarliaError) as e:
        logger.error("/facturables : erreur Karlia", extra={"erreur": str(e)})
        raise _karlia_to_http(e) from e
    return groupes


@router.get("", response_model=List[FactureListItem])
def lister_factures(
    statut: Optional[str] = Query(default=None, description="Filtre statut (brouillon | validee)"),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    query = db.query(FactureFournisseur)
    if statut is not None:
        query = query.filter(FactureFournisseur.statut == statut)
    factures = query.order_by(FactureFournisseur.created_at.desc()).all()

    # Comptage des lignes par facture en une seule sous-requête.
    if not factures:
        return []
    ids = [f.id for f in factures]
    counts = dict(
        db.query(
            FactureFournisseurLigne.id_facture_fournisseur,
            func.count(FactureFournisseurLigne.id),
        )
        .filter(FactureFournisseurLigne.id_facture_fournisseur.in_(ids))
        .group_by(FactureFournisseurLigne.id_facture_fournisseur)
        .all()
    )
    return [
        FactureListItem(
            id=f.id,
            id_fournisseur_karlia=f.id_fournisseur_karlia,
            nom_fournisseur=f.nom_fournisseur,
            statut=f.statut,
            date_facture=f.date_facture,
            reference=f.reference,
            total_ht=f.total_ht,
            total_tva=f.total_tva,
            total_ttc=f.total_ttc,
            created_at=f.created_at,
            updated_at=f.updated_at,
            nb_lignes=int(counts.get(f.id, 0)),
        )
        for f in factures
    ]


@router.get("/{facture_id}", response_model=FactureResponse)
def obtenir_facture(
    facture_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    facture = (
        db.query(FactureFournisseur)
        .options(joinedload(FactureFournisseur.lignes))
        .filter(FactureFournisseur.id == facture_id)
        .first()
    )
    if facture is None:
        raise HTTPException(status_code=404, detail=f"Facture {facture_id} introuvable")
    return _to_response(facture)


@router.post("", response_model=FactureResponse, status_code=201)
async def creer_brouillon(
    payload: FactureCreateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Crée une facture fournisseur au statut brouillon.

    Recontrôle côté serveur : toutes les lignes doivent appartenir au même
    fournisseur (`id_fournisseur` du payload), et chaque quantité doit
    respecter la borne `quantite_restante` (livré − cumul facturé). Les
    écarts lèvent un 422.
    """
    lignes_dicts = [l.model_dump() for l in payload.lignes]
    try:
        facture = await karlia_factures_fournisseurs_service.creer_brouillon(
            db, id_fournisseur=payload.id_fournisseur,
            lignes_selectionnees=lignes_dicts,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (KarliaBodyError, KarliaError) as e:
        raise _karlia_to_http(e) from e
    return _to_response(facture)


@router.put("/{facture_id}", response_model=FactureResponse)
async def mettre_a_jour_brouillon(
    facture_id: int,
    payload: FactureUpdateRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    lignes_dicts = [l.model_dump() for l in payload.lignes]
    try:
        facture = await karlia_factures_fournisseurs_service.mettre_a_jour_brouillon(
            db, id_facture=facture_id, lignes_selectionnees=lignes_dicts,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (KarliaBodyError, KarliaError) as e:
        raise _karlia_to_http(e) from e
    return _to_response(facture)


@router.post("/{facture_id}/valider", response_model=FactureResponse)
async def valider(
    facture_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Valide un brouillon : incrémente le pointage anti-doublon par ligne,
    passe le statut à 'validee'. N'appelle PAS Karlia (émission non
    disponible, en attente du support Karlia).
    """
    try:
        facture = await karlia_factures_fournisseurs_service.valider_facture(
            db, id_facture=facture_id,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except (KarliaBodyError, KarliaError) as e:
        raise _karlia_to_http(e) from e
    return _to_response(facture)


@router.delete("/{facture_id}", status_code=204)
def supprimer(
    facture_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    try:
        karlia_factures_fournisseurs_service.supprimer_brouillon(
            db, id_facture=facture_id
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return None
