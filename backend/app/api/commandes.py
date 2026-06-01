"""
Routes API — Commandes (bons de commande validés Karlia)

Depuis la refonte v3.1, la source de synchronisation est les BONS DE COMMANDE
Karlia (type=2) et non plus les devis (type=1). Les noms d'attributs publics
(reference_devis, date_devis, date_acceptation) sont CONSERVÉS pour
compatibilité descendante de l'API et du frontend.

GET  /api/commandes/sync              → Synchronise les BC depuis Karlia
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
GET  /api/commandes/{id}/pdf          → Télécharger le PDF du bon de commande
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from typing import Optional, List
from pydantic import BaseModel
from datetime import date, datetime
from decimal import Decimal
import logging
import httpx

from app.core.database import get_db
from app.core.security import require_authenticated, require_role
from app.services.karlia_service import karlia
from app.models.models import Commande, CommandeLigne, Prestation, Contrat, Formateur
from app.services.karlia_devis_service import karlia_devis_service
from app.services.routage_service import (
    destination_par_defaut,
    eclater_ligne_en_prestations,
    DESTINATIONS_VALIDES,
    DESTINATION_A_PLANIFIER,
    DESTINATION_CONTRAT,
    DESTINATION_FACTURATION_DIRECTE,
    DESTINATION_INTITULE,
)

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
    # Catégorie (snapshot Karlia)
    id_product_category: Optional[int] = None
    product_category: Optional[str] = None
    # Marqueur Karlia products_list[i].section (0 = vraie ligne, 1 = intitulé/
    # section/sous-total, None = inconnu). Exposé pour permettre au frontend
    # de griser/désactiver les lignes d'intitulé. Cf. diag_section_universel.md.
    section_karlia: Optional[int] = None
    # destination = valeur stockée (NULL tant que pas routé)
    # destination_defaut = valeur calculée par le routage par défaut (jamais NULL)
    # → le frontend pré-coche destination_defaut quand destination est NULL.
    destination: Optional[str] = None
    destination_defaut: str = DESTINATION_FACTURATION_DIRECTE

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
    nb_prestations: int = 0
    nb_prestations_attribuees: int = 0
    nb_prestations_planifiees: int = 0
    formateur_id: Optional[int] = None
    formateur_nom: Optional[str] = None
    # Comptage des formateur_id distincts non-NULL sur les prestations de la
    # commande. Le frontend l'utilise pour afficher : 0 → "Non attribué",
    # 1 → formateur_nom, ≥2 → "N formateurs". Calculé en mémoire à partir des
    # prestations déjà chargées (joinedload), pas de N+1 sur la liste paginée.
    nb_formateurs_distincts: int = 0
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


class LigneAFacturerResponse(BaseModel):
    """Une ligne 'facturation_directe' non encore facturée (écran Terminées).

    On expose l'identité de la ligne ET le contexte commande nécessaire au
    frontend pour grouper/contraindre la sélection par client (mono-client
    Karlia) et afficher l'origine. `karlia_customer_id` est la clé de
    regroupement : une facture Karlia = un seul client.
    """
    ligne_id: int
    commande_id: int
    commande_reference: Optional[str] = None
    karlia_customer_id: Optional[int] = None
    client_nom: Optional[str] = None
    designation: Optional[str] = None
    quantite: Optional[Decimal] = None
    prix_unitaire_ht: Optional[Decimal] = None
    taux_tva: Optional[Decimal] = None
    montant_ht: Optional[Decimal] = None
    montant_ttc: Optional[Decimal] = None
    date_acceptation: Optional[date] = None
    ordre: Optional[int] = None


class LigneAFacturerListResponse(BaseModel):
    items: List[LigneAFacturerResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class FacturerLignesPayload(BaseModel):
    """Sélection de lignes à facturer ensemble (une seule facture Karlia)."""
    ligne_ids: List[int]


class FacturerLignesResponse(BaseModel):
    facture_karlia_id: Optional[str] = None
    facture_karlia_ref: Optional[str] = None
    nb_lignes_facturees: int
    ligne_ids: List[int]


class CommandeStats(BaseModel):
    nouvelles: int = 0
    a_planifier: int = 0
    planifiees: int = 0

    contrats_a_creer: int = 0
    total: int = 0


class SyncDevisResult(BaseModel):
    """
    Résultat d'une sync Karlia → commandes locales.

    Les noms de champs commencent par "devis_" / "nouveaux_devis" pour
    compatibilité historique avec le frontend. Depuis v3.1, ils comptent
    en réalité des BONS DE COMMANDE.
    """
    success: bool
    nouveaux_devis: int = 0
    devis_mis_a_jour: int = 0
    devis_ignores: int = 0
    ignores_avances: int = 0
    documents_rejetes_par_type: int = 0
    opportunites_marquees: int = 0
    pdf_url_renseigne: int = 0
    pdf_url_absent: int = 0
    erreurs: List[str] = []
    message: str = ""


class CommandeValidation(BaseModel):
    """
    Ancien schéma global (compat descendante).

    Un type_traitement unique pour toute la commande. Toujours accepté en
    fallback quand le payload nouveau (`lignes`) n'est PAS fourni.
    """
    type_traitement: str  # 'a_planifier' ou 'sans_planification'
    necessite_contrat: bool = False


class CommandeRoutageLigne(BaseModel):
    """Routage d'une ligne unique dans le nouveau payload de validation."""
    ligne_id: int
    destination: str  # 'a_planifier' | 'contrat' | 'facturation_directe'


class CommandeRoutage(BaseModel):
    """
    Nouveau schéma de validation par ligne. Si `lignes` est fourni, on emprunte
    le chemin par-ligne (cf. valider_commande). type_traitement et
    necessite_contrat sont ignorés dans ce mode (la destination par ligne
    porte toute l'information).
    """
    type_traitement: Optional[str] = None
    necessite_contrat: Optional[bool] = None
    lignes: Optional[List[CommandeRoutageLigne]] = None


class CommandePlanification(BaseModel):
    date_planifiee: date
    intervenant_id: Optional[int] = None
    intervenant_nom: Optional[str] = None
    notes_planification: Optional[str] = None


class AffectationFormateurItem(BaseModel):
    """Une affectation prestation → formateur dans le payload par-prestation.

    formateur_id à None = désaffecter explicitement la prestation. Une
    prestation NON listée dans le payload n'est PAS touchée (affectation
    partielle autorisée, cf. POST /commandes/{id}/affecter-formateurs).
    """
    prestation_id: int
    formateur_id: Optional[int] = None


class AffectationFormateursPayload(BaseModel):
    affectations: List[AffectationFormateurItem]


class AffectationFormateursResult(BaseModel):
    """Réponse de POST /commandes/{id}/affecter-formateurs.

    `avertissements` liste les prestation_id dont la réaffectation a quand
    même été appliquée mais qui étaient déjà 'planifiee' (ou avaient une
    date planifiée posée) — le frontend prévient l'utilisateur qu'un
    événement agenda associé devra peut-être être recalé manuellement.
    """
    commande: CommandeResponse
    avertissements: List[int] = []


# ── Helpers ──────────────────────────────────────────────────────────────────

def _commande_to_response(commande: Commande) -> CommandeResponse:
    # Compter les prestations
    prestations = commande.prestations if hasattr(commande, 'prestations') and commande.prestations else []
    nb_prestations = len(prestations)
    nb_attribuees = sum(1 for p in prestations if p.formateur_id is not None)
    nb_planifiees = sum(1 for p in prestations if p.statut == 'planifiee' or p.statut == 'realisee')
    # Nombre de formateurs distincts (non-NULL) sur les prestations. Permet
    # au frontend d'afficher "N formateurs" quand la commande est répartie.
    nb_formateurs_distincts = len({
        p.formateur_id for p in prestations if p.formateur_id is not None
    })

    return CommandeResponse(
        id=commande.id,
        karlia_document_id=commande.karlia_document_id,
        karlia_customer_id=commande.karlia_customer_id,
        karlia_opportunity_id=commande.karlia_opportunity_id,
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
        pdf_disponible=bool(commande.pdf_url),
        pdf_url=commande.pdf_url,
        nb_prestations=nb_prestations,
        nb_prestations_attribuees=nb_attribuees,
        nb_prestations_planifiees=nb_planifiees,
        formateur_id=commande.formateur_id,
        formateur_nom=f"{commande.formateur.prenom or ''} {commande.formateur.nom}".strip() if commande.formateur else None,
        nb_formateurs_distincts=nb_formateurs_distincts,
        date_import=commande.date_import,
        date_validation=commande.date_validation,
        lignes=[_ligne_to_response(l) for l in commande.lignes]
    )


def _ligne_to_response(ligne: CommandeLigne) -> CommandeLigneResponse:
    """Sérialise une CommandeLigne en y ajoutant la destination par défaut calculée."""
    return CommandeLigneResponse(
        id=ligne.id,
        commande_id=ligne.commande_id,
        karlia_product_id=ligne.karlia_product_id,
        designation=ligne.designation,
        description=ligne.description,
        quantite=ligne.quantite,
        unite=ligne.unite,
        prix_unitaire_ht=ligne.prix_unitaire_ht,
        taux_tva=ligne.taux_tva,
        montant_ht=ligne.montant_ht,
        montant_tva=ligne.montant_tva,
        montant_ttc=ligne.montant_ttc,
        ordre=ligne.ordre,
        id_product_category=ligne.id_product_category,
        product_category=ligne.product_category,
        section_karlia=ligne.section_karlia,
        destination=ligne.destination,
        # Passe section_karlia au routage par défaut : section==1 force
        # 'intitule' indépendamment de la catégorie.
        destination_defaut=destination_par_defaut(
            ligne.id_product_category,
            ligne.product_category,
            section=ligne.section_karlia,
        ),
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
async def sync_devis_karlia(
    force_full: bool = Query(False),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Synchronise les bons de commande validés depuis Karlia."""
    try:
        result = await karlia_devis_service.sync_devis_acceptes(db, force_full=force_full)
        return SyncDevisResult(**result)
    except Exception as e:
        logger.error(f"Erreur sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats", response_model=CommandeStats)
async def get_commandes_stats(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
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
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Liste des nouvelles commandes à traiter."""
    return _get_commandes_by_statut(db, "nouvelle", page, page_size, search)


@router.get("/a-planifier", response_model=CommandeListResponse)
async def get_commandes_a_planifier(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Liste des commandes à planifier."""
    return _get_commandes_by_statut(db, "a_planifier", page, page_size, search)


@router.get("/planifiees", response_model=CommandeListResponse)
async def get_commandes_planifiees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Liste des commandes planifiées."""
    return _get_commandes_by_statut(db, "planifiee", page, page_size, search)


@router.get("/terminees", response_model=CommandeListResponse)
async def get_commandes_terminees(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Liste des commandes terminées (prestations réalisées, à facturer)."""
    return _get_commandes_by_statut(db, "deployee", page, page_size, search)




@router.get("/contrats-a-creer", response_model=CommandeListResponse)
async def get_contrats_a_creer(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
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


@router.get("/lignes-a-facturer", response_model=LigneAFacturerListResponse)
async def get_lignes_a_facturer(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Liste des LIGNES routées 'facturation_directe' non encore facturées.

    Granularité = la ligne (et non la commande). Indépendant du statut de la
    commande parente : une commande mixte (lignes a_planifier/contrat + lignes
    facturation_directe) expose ici uniquement ses lignes facturation directe
    non facturées. Une ligne facturée (facture_karlia_id non NULL) disparaît.

    NB : cette route DOIT rester déclarée avant GET /{commande_id} (segment
    unique typé int) sinon "lignes-a-facturer" serait capturé par le catch-all.
    """
    query = (
        db.query(CommandeLigne, Commande)
        .join(Commande, Commande.id == CommandeLigne.commande_id)
        .filter(
            CommandeLigne.destination == DESTINATION_FACTURATION_DIRECTE,
            CommandeLigne.facture_karlia_id.is_(None),
            # Exclusion des intitulés Karlia (titres de section / sous-totaux,
            # montant 0€) : seul le VRAI MARQUEUR section_karlia fait foi, jamais
            # le montant. section_karlia=1 = intitulé → exclu. On ne garde que
            # les vraies lignes (0) et les lignes non encore qualifiées (NULL,
            # anciennes commandes). Cf. repeuplement ciblé des intitulés non
            # marqués (ex BC26-0090 : ids 1042/1043/1045/1047 passés à 1).
            or_(CommandeLigne.section_karlia.is_(None), CommandeLigne.section_karlia == 0),
        )
    )
    if search:
        query = query.filter(or_(
            Commande.client_nom.ilike(f"%{search}%"),
            Commande.reference_devis.ilike(f"%{search}%"),
        ))

    total = query.count()
    total_pages = (total + page_size - 1) // page_size
    rows = (
        query
        .order_by(Commande.date_acceptation.desc().nullslast(), CommandeLigne.commande_id.desc(), CommandeLigne.ordre.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        LigneAFacturerResponse(
            ligne_id=ligne.id,
            commande_id=ligne.commande_id,
            commande_reference=commande.reference_devis,
            karlia_customer_id=commande.karlia_customer_id,
            client_nom=commande.client_nom,
            designation=ligne.designation,
            quantite=ligne.quantite,
            prix_unitaire_ht=ligne.prix_unitaire_ht,
            taux_tva=ligne.taux_tva,
            montant_ht=ligne.montant_ht,
            montant_ttc=ligne.montant_ttc,
            date_acceptation=commande.date_acceptation,
            ordre=ligne.ordre,
        )
        for ligne, commande in rows
    ]
    return LigneAFacturerListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.post("/facturer-lignes", response_model=FacturerLignesResponse)
async def facturer_lignes(
    payload: FacturerLignesPayload,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Émet UNE facture Karlia BROUILLON pour une sélection de lignes.

    MONO-COMMANDE : une facture ne couvre qu'UNE SEULE commande (décision
    métier v3.5.0). Cela rend la contrainte mono-client automatique (une
    commande = un client) et permet de poser sans ambiguïté l'id_opportunity
    de la commande (parité avec l'ancien facturer_commande).

    VALIDATION intégrale AVANT tout effet de bord (aucune écriture, aucun appel
    Karlia tant que la sélection n'est pas entièrement valide). APPLICATION en
    transaction unique : succès Karlia → marquage de TOUTES les lignes ; échec
    Karlia → rollback complet, jamais de marquage partiel.

    Ne touche PAS au statut de la commande parente : les lignes facturation
    directe vivent indépendamment des lignes a_planifier / contrat.
    """
    # ── VALIDATION (aucun effet de bord) ─────────────────────────────────────
    if not payload.ligne_ids:
        raise HTTPException(status_code=400, detail="Aucune ligne sélectionnée")

    # Dédoublonnage défensif tout en conservant l'ordre d'origine.
    ligne_ids = list(dict.fromkeys(payload.ligne_ids))

    lignes = (
        db.query(CommandeLigne)
        .options(joinedload(CommandeLigne.commande))
        .filter(CommandeLigne.id.in_(ligne_ids))
        .all()
    )
    lignes_par_id = {l.id: l for l in lignes}

    # Existence : chaque id demandé doit avoir été retrouvé.
    manquants = [lid for lid in ligne_ids if lid not in lignes_par_id]
    if manquants:
        raise HTTPException(status_code=404, detail=f"Lignes introuvables : {manquants}")

    commande_ids = set()
    customer_ids = set()
    for lid in ligne_ids:
        ligne = lignes_par_id[lid]
        if ligne.destination != DESTINATION_FACTURATION_DIRECTE:
            raise HTTPException(
                status_code=400,
                detail=f"Ligne {lid} n'est pas en facturation directe (destination={ligne.destination!r})",
            )
        if ligne.facture_karlia_id is not None:
            raise HTTPException(
                status_code=400,
                detail=f"Ligne {lid} est déjà facturée (facture {ligne.facture_karlia_ref or ligne.facture_karlia_id})",
            )
        commande = ligne.commande
        if commande is None or not commande.karlia_customer_id:
            raise HTTPException(
                status_code=400,
                detail=f"Ligne {lid} : client Karlia non renseigné sur la commande",
            )
        commande_ids.add(ligne.commande_id)
        customer_ids.add(commande.karlia_customer_id)

    # MONO-COMMANDE : une facture ne peut couvrir qu'une seule commande.
    if len(commande_ids) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                "Une facture ne peut couvrir qu'une seule commande à la fois. "
                f"Sélection actuelle : {len(commande_ids)} commandes "
                f"(ids {sorted(commande_ids)})."
            ),
        )

    # MONO-CLIENT : redondant avec mono-commande (1 commande = 1 client) mais
    # conservé comme garde-fou inoffensif.
    if len(customer_ids) > 1:
        raise HTTPException(
            status_code=400,
            detail=(
                "Sélection multi-clients impossible : une facture Karlia = un seul "
                f"client. Clients distincts dans la sélection : {sorted(customer_ids)}"
            ),
        )

    commande_unique = lignes_par_id[ligne_ids[0]].commande
    client_karlia_id = commande_unique.karlia_customer_id

    # ── Construction du payload Karlia ───────────────────────────────────────
    reference = commande_unique.reference_devis or f"CMD-{commande_unique.id}"

    # Exclusion défensive des intitulés (section_karlia==1 ou destination
    # 'intitule') : titres de section / sous-totaux à 0€ qui produiraient des
    # lignes parasites sur la facture. Parité avec facturer_commande. Seules les
    # lignes réellement facturables sont envoyées ET marquées.
    ids_facturables = [
        lid for lid in ligne_ids
        if not (lignes_par_id[lid].section_karlia == 1
                or lignes_par_id[lid].destination == DESTINATION_INTITULE)
    ]
    if not ids_facturables:
        raise HTTPException(status_code=400, detail="Aucune ligne facturable (intitulés exclus)")

    montant_ht_total = sum(float(lignes_par_id[lid].montant_ht or 0) for lid in ids_facturables)

    lignes_karlia = []
    for lid in ids_facturables:
        ligne = lignes_par_id[lid]
        lignes_karlia.append({
            "id_product": ligne.karlia_product_id,
            "quantity": float(ligne.quantite or 1),
            "unit_price": float(ligne.prix_unitaire_ht or 0),
            "vat_rate": float(ligne.taux_tva or 20),
            "description": ligne.designation or "",
        })

    # ── APPLICATION (transaction unique) ─────────────────────────────────────
    try:
        # id_status=0 (BROUILLON) est le défaut de creer_facture (cf.
        # karlia_service.creer_facture, payload id_status:0). Émission en
        # brouillon impérative : la facture reste éditable côté Karlia.
        result = await karlia.creer_facture(
            client_karlia_id=str(client_karlia_id),
            lignes=lignes_karlia,
            reference_contrat=reference,
            date_echeance=date.today(),
            montant_ht=montant_ht_total,
            description=f"Facturation prestation(s) - {reference}",
            # Lien à l'opportunité Karlia de la commande (parité avec l'ancien
            # facturer_commande). None si la commande n'a pas d'opportunité.
            id_opportunity=commande_unique.karlia_opportunity_id,
        )
    except Exception as e:
        # Aucune écriture n'a eu lieu avant cet appel → rien à rollback côté DB,
        # mais on garantit l'absence de marquage partiel.
        raise HTTPException(status_code=500, detail=f"Erreur Karlia: {str(e)}")

    try:
        facture_id = str(result.get("id", ""))
        facture_ref = result.get("reference", "")
        now = datetime.utcnow()
        for lid in ids_facturables:
            ligne = lignes_par_id[lid]
            ligne.facture_karlia_id = facture_id
            ligne.facture_karlia_ref = facture_ref
            ligne.date_facturee = now
        db.commit()
    except Exception as e:
        db.rollback()
        # La facture Karlia (brouillon) a été créée mais le marquage local a
        # échoué : on remonte une 500 explicite pour intervention manuelle
        # (la facture brouillon est supprimable côté Karlia).
        raise HTTPException(
            status_code=500,
            detail=(
                f"Facture Karlia {facture_ref or facture_id} créée mais marquage local "
                f"échoué (aucune ligne marquée) : {e}"
            ),
        )

    return FacturerLignesResponse(
        facture_karlia_id=facture_id,
        facture_karlia_ref=facture_ref,
        nb_lignes_facturees=len(ids_facturables),
        ligne_ids=ids_facturables,
    )


@router.get("/{commande_id}", response_model=CommandeResponse)
async def get_commande(
    commande_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """Récupère les détails d'une commande."""
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    return _commande_to_response(commande)


@router.post("/{commande_id}/valider", response_model=CommandeResponse)
async def valider_commande(
    commande_id: int,
    payload: CommandeRoutage,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Valide une commande, deux chemins selon le payload :

    1) Nouveau chemin par-ligne (`lignes` présent) : chaque ligne reçoit sa
       propre `destination` ∈ {'a_planifier', 'contrat', 'facturation_directe'}.
       - 'a_planifier' → éclatement unitaire en N prestations (cf.
         routage_service.eclater_ligne_en_prestations).
       - 'contrat' → marque la commande necessite_contrat=True (mécanisme
         existant, le contrat reste créé manuellement via le tunnel 4 étapes).
       - 'facturation_directe' → AUCUN déclenchement automatique ici. La
         facturation Karlia reste pilotée par le circuit existant
         (POST /commandes/{id}/facturer).
       Toute la validation s'effectue dans une transaction unique.

    2) Ancien chemin global (`lignes` absent) : payload {type_traitement,
       necessite_contrat}. Compatibilité descendante stricte avec
       CommandeValidation.

    Statut final de la commande :
      - au moins une ligne 'a_planifier' → 'a_planifier'
        (le tunnel planification habituel prend le relais)
      - sinon, au moins une 'contrat' → 'a_planifier' aussi (les contrats
        nécessitent toujours une intervention humaine via /contrats-a-creer).
        On garde 'a_planifier' pour rester cohérent avec le statut historique
        des commandes en attente d'action.
      - sinon → 'deployee' (tout est en facturation directe, rien à faire
        de plus côté SGI, la commande sort des écrans actifs).

    Les lignes routées 'intitule' (titres de section/sous-totaux Karlia) sont
    acceptées mais ne déclenchent AUCUN effet : pas de prestation, pas de
    necessite_contrat, et ignorées dans le calcul du statut final.

    Marquage "Traité" Karlia (custom field 66505, porté par l'opportunité) :
    DÉPLACÉ ICI depuis la sync. Posé en BEST-EFFORT après le commit de
    routage, uniquement dans le chemin par-ligne et uniquement quand il ne
    reste plus aucune commande 'nouvelle' sur l'opportunité (garde-fou
    multi-BC). Un échec côté Karlia ne fait pas échouer la validation : le
    routage SGI est déjà committé, on logge un warning. Le chemin global
    (compat descendante) ne pose PAS le marquage : il n'est plus appelé par
    le frontend depuis l'écran de routage v3.3.0 et n'a pas la sémantique
    "SGI a routé".
    """
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    if commande.statut != "nouvelle":
        raise HTTPException(status_code=400, detail="Cette commande a déjà été validée")

    # ─── Chemin par-ligne (nouveau) ─────────────────────────────────────
    if payload.lignes is not None:
        # Index des lignes de la commande pour validation/lookup
        lignes_commande = {l.id: l for l in commande.lignes}

        # Validation préalable : tout doit être OK avant tout side-effect
        for item in payload.lignes:
            if item.ligne_id not in lignes_commande:
                raise HTTPException(
                    status_code=400,
                    detail=f"ligne_id {item.ligne_id} n'appartient pas à cette commande",
                )
            if item.destination not in DESTINATIONS_VALIDES:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"destination invalide '{item.destination}' pour ligne {item.ligne_id} "
                        f"(attendu : {list(DESTINATIONS_VALIDES)})"
                    ),
                )

        # Couverture : on s'assure que CHAQUE ligne de la commande est routée
        ids_routes = {item.ligne_id for item in payload.lignes}
        ids_manquants = set(lignes_commande.keys()) - ids_routes
        if ids_manquants:
            raise HTTPException(
                status_code=400,
                detail=f"Lignes non routées : {sorted(ids_manquants)}. "
                       f"Toutes les lignes doivent recevoir une destination.",
            )

        # Application dans une seule transaction
        try:
            has_a_planifier = False
            has_contrat = False

            for item in payload.lignes:
                ligne = lignes_commande[item.ligne_id]
                ligne.destination = item.destination

                if item.destination == DESTINATION_A_PLANIFIER:
                    has_a_planifier = True
                    eclater_ligne_en_prestations(db, ligne)
                elif item.destination == DESTINATION_CONTRAT:
                    has_contrat = True
                # facturation_directe : rien d'autre à faire ici (cf. docstring)
                # intitule           : ligne neutre, aucun effet (pas de
                #                       prestation, pas de contrat, pas de
                #                       comptage pour le statut).

            commande.date_validation = datetime.utcnow()
            commande.necessite_contrat = has_contrat
            # type_traitement reste à fin documentaire : valeur agrégée.
            # Les lignes 'intitule' sont ignorées dans ce calcul : une
            # commande dont toutes les vraies lignes sont en facturation
            # directe (et le reste en intitulés) reste 'deployee'.
            if has_a_planifier:
                commande.type_traitement = DESTINATION_A_PLANIFIER
                commande.statut = "a_planifier"
            elif has_contrat:
                commande.type_traitement = DESTINATION_CONTRAT
                commande.statut = "a_planifier"
            else:
                commande.type_traitement = DESTINATION_FACTURATION_DIRECTE
                commande.statut = "deployee"

            db.commit()
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error(f"Erreur routage par-ligne commande {commande_id} : {e}")
            raise HTTPException(status_code=500, detail=f"Erreur de routage : {e}")

        # ── Marquage "Traité" Karlia — best-effort, post-commit ─────────────
        # Pourquoi ici plutôt qu'à l'import : pour que tant que SGI n'a pas
        # validé le routage, le BC apparaisse "non Traité" côté CRM Karlia
        # (le commercial voit que SGI n'a pas fini). Une fois validé → SGI
        # coche Traité → le BC sort du flux côté CRM.
        # Garde-fou multi-BC : 66505 est porté par l'OPPORTUNITÉ. Si dans le
        # futur Karlia permet plusieurs BC sur une même opportunité, on
        # n'allume Traité qu'une fois TOUTES les commandes de l'opp sorties
        # de 'nouvelle' — sinon on signalerait à tort "fini" alors qu'il
        # reste des BC frères à router.
        # Best-effort : échec Karlia → warning, JAMAIS d'échec de validation
        # (le routage SGI est déjà committé en DB, ne pas le défaire).
        if commande.karlia_opportunity_id:
            reste_nouvelle = db.query(Commande).filter(
                Commande.karlia_opportunity_id == commande.karlia_opportunity_id,
                Commande.statut == "nouvelle",
                Commande.id != commande.id,
            ).first()
            if reste_nouvelle is None:
                try:
                    async with httpx.AsyncClient(timeout=10.0) as http_client:
                        await karlia_devis_service._marquer_opportunity_traitee(
                            http_client, str(commande.karlia_opportunity_id)
                        )
                except Exception as e:
                    logger.warning(
                        f"Marquage 'Traité' Karlia échoué (best-effort) pour "
                        f"commande {commande_id} "
                        f"(opp={commande.karlia_opportunity_id}) : {e!r}"
                    )
            else:
                logger.info(
                    f"Marquage 'Traité' différé pour commande {commande_id} : "
                    f"il reste au moins une commande 'nouvelle' sur "
                    f"l'opportunité {commande.karlia_opportunity_id} "
                    f"(id={reste_nouvelle.id})"
                )

        db.refresh(commande)
        return _commande_to_response(commande)

    # ─── Chemin ancien (global) ─────────────────────────────────────────
    # NB : ce chemin (compat descendante) NE pose PAS le marquage "Traité"
    # Karlia. Il n'est plus utilisé par le frontend depuis v3.3.0 et n'a pas
    # la sémantique "SGI a routé par ligne" qui justifie le signal CRM.
    type_traitement = payload.type_traitement
    if type_traitement not in ["a_planifier", "sans_planification"]:
        raise HTTPException(status_code=400, detail="type_traitement invalide")

    commande.type_traitement = type_traitement
    commande.necessite_contrat = payload.necessite_contrat or False
    commande.date_validation = datetime.utcnow()
    commande.statut = "a_planifier" if type_traitement == "a_planifier" else "deployee"

    db.commit()
    db.refresh(commande)
    return _commande_to_response(commande)


@router.post("/{commande_id}/planifier", response_model=CommandeResponse)
async def planifier_commande(
    commande_id: int,
    planification: CommandePlanification,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
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


@router.post(
    "/{commande_id}/affecter-formateurs",
    response_model=AffectationFormateursResult,
)
async def affecter_formateurs(
    commande_id: int,
    payload: AffectationFormateursPayload,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Affecte un formateur PAR PRESTATION sur une commande.

    Use case : remplacer l'affectation globale "1 formateur pour toute la
    commande" (POST /api/prestations/reattribuer-commande/{id}, conservé en
    raccourci) par une répartition fine. Pour chaque prestation listée dans
    le payload, on pose son `formateur_id` (ou NULL pour désaffecter).

    Semantique :
      - Affectation PARTIELLE autorisée : une prestation absente du payload
        n'est PAS touchée. Cela permet d'ajuster une seule prestation sans
        renvoyer toutes les autres.
      - Réaffectation AUTORISÉE même sur une prestation déjà 'planifiee' (ou
        avec date_planifiee posée). Dans ce cas la prestation_id est ajoutée
        à `avertissements` dans la réponse : le frontend prévient
        l'utilisateur qu'un événement agenda associé devra peut-être être
        recalé. L'affectation est appliquée quoi qu'il en soit.
      - Validation préalable : tout doit passer AVANT le premier side-effect
        (404/400 sans aucune écriture).

    Recalcul de `commande.formateur_id` (cohérence d'affichage avec la liste) :
      - 0 prestation avec formateur → NULL
      - exactement 1 formateur distinct → ce formateur
      - ≥2 formateurs distincts → NULL (le champ `nb_formateurs_distincts` du
        schéma prend le relais : le frontend affiche "N formateurs")
    """
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")

    # On n'affecte que sur les commandes encore dans le flow actif. Une
    # commande facturée/terminée ne doit plus voir ses prestations bouger.
    statuts_actifs = ("a_planifier", "planifiee")
    if commande.statut not in statuts_actifs:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Statut commande '{commande.statut}' incompatible avec une "
                f"affectation (attendu : {list(statuts_actifs)})"
            ),
        )

    # Index des prestations de la commande pour validation et application.
    prestations_par_id = {p.id: p for p in commande.prestations}

    # Pré-charge en UNE requête les formateurs actifs référencés dans le
    # payload (évite N requêtes ponctuelles dans la boucle de validation).
    formateur_ids_demandes = {
        item.formateur_id for item in payload.affectations
        if item.formateur_id is not None
    }
    formateurs_actifs: set = set()
    if formateur_ids_demandes:
        rows = db.query(Formateur.id).filter(
            Formateur.id.in_(formateur_ids_demandes),
            Formateur.actif == True,  # noqa: E712 (SQLAlchemy comparison)
        ).all()
        formateurs_actifs = {r.id for r in rows}

    # Validation préalable : aucun side-effect avant d'avoir tout vérifié.
    for item in payload.affectations:
        if item.prestation_id not in prestations_par_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"prestation_id {item.prestation_id} n'appartient pas à "
                    f"cette commande (id={commande_id})"
                ),
            )
        if item.formateur_id is not None and item.formateur_id not in formateurs_actifs:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"formateur_id {item.formateur_id} inexistant ou inactif"
                ),
            )

    # Application dans une seule transaction.
    try:
        avertissements: List[int] = []
        for item in payload.affectations:
            prestation = prestations_par_id[item.prestation_id]
            # Avertissement si la prestation est déjà engagée dans le flow
            # de planification (statut planifiee ou date posée). On applique
            # quand même la réaffectation, mais on retourne l'id pour que
            # le frontend signale qu'un évent agenda peut nécessiter un
            # recalage manuel.
            if prestation.statut == "planifiee" or prestation.date_planifiee is not None:
                avertissements.append(prestation.id)
            prestation.formateur_id = item.formateur_id
            prestation.updated_at = datetime.utcnow()

        # Recalcul de commande.formateur_id sur l'ENSEMBLE des prestations
        # actives (on ignore les 'realisee' qui n'ont plus à influencer
        # l'affichage du formateur "en cours").
        formateurs_actuels = {
            p.formateur_id
            for p in commande.prestations
            if p.formateur_id is not None
            and p.statut in ("a_planifier", "planifiee")
        }
        if len(formateurs_actuels) == 1:
            commande.formateur_id = next(iter(formateurs_actuels))
        else:
            # 0 ou ≥2 → NULL. nb_formateurs_distincts gère l'affichage côté
            # liste (cf. CommandeResponse).
            commande.formateur_id = None
        commande.updated_at = datetime.utcnow()

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            f"Erreur affectation formateurs commande {commande_id} : {e}"
        )
        raise HTTPException(
            status_code=500, detail=f"Erreur d'affectation : {e}"
        )

    db.refresh(commande)
    return AffectationFormateursResult(
        commande=_commande_to_response(commande),
        avertissements=sorted(avertissements),
    )


@router.post("/{commande_id}/terminer", response_model=CommandeResponse)
async def terminer_commande(
    commande_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
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
async def lier_contrat_commande(
    commande_id: int,
    contrat_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
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
async def get_commande_pdf(
    commande_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Proxie le PDF du bon de commande hébergé par Karlia.

    Pourquoi un proxy plutôt qu'une RedirectResponse ?
    Karlia ne renvoie aucun header CORS sur get-file.php. Quand le front
    appelle cet endpoint via fetch+blob (helper openPdfWithAuth, requis par
    le RBAC pour porter le JWT), le browser suivait la 307 cross-origin et
    bloquait la lecture du blob (onglet vide). En proxyant Karlia depuis le
    backend, on reste same-origin côté navigateur, le RBAC reste appliqué
    via require_role, et le PDF devient lisible côté JS.

    L'URL Karlia (get-file.php?token=...) est auto-portée par son token de
    query : aucun en-tête d'auth supplémentaire n'est nécessaire pour la
    récupérer.
    """
    commande = db.query(Commande).filter(Commande.id == commande_id).first()
    if not commande:
        raise HTTPException(status_code=404, detail="Commande non trouvée")
    if not commande.pdf_url:
        raise HTTPException(status_code=404, detail="PDF non disponible pour cette commande")

    nom_fichier = f"{commande.reference_devis or f'cmd-{commande.id}'}.pdf"

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            karlia_resp = await client.get(commande.pdf_url)
    except httpx.HTTPError as e:
        logger.error(
            f"PDF Karlia erreur réseau pour commande {commande_id} "
            f"(ref={commande.reference_devis}) : {e!r}"
        )
        raise HTTPException(status_code=502, detail="PDF indisponible côté Karlia (réseau)")

    if karlia_resp.status_code != 200:
        logger.error(
            f"PDF Karlia HTTP {karlia_resp.status_code} pour commande {commande_id} "
            f"(ref={commande.reference_devis})"
        )
        raise HTTPException(status_code=502, detail="PDF indisponible côté Karlia")

    # On force application/pdf : Karlia renvoie 'application/force-download'
    # qui déclencherait un téléchargement systématique alors qu'on veut
    # l'affichage inline dans l'onglet du navigateur.
    return Response(
        content=karlia_resp.content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nom_fichier}"'},
    )

@router.post("/{commande_id}/facturer")
async def facturer_commande(
    commande_id: int,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
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

    # Préparer les lignes pour Karlia.
    # EXCLUSION : les lignes d'intitulé Karlia (section_karlia == 1) et celles
    # routées explicitement 'intitule' n'ont pas de valeur facturable
    # (montant_ht=0 chez Karlia, titre de section ou sous-total). Les inclure
    # produirait des lignes parasites sur la facture émise. Cf. Option B
    # diag_section_universel.md : on garde tout en DB, on filtre uniquement
    # aux points de sortie (routage et facturation).
    lignes_karlia = []
    for ligne in commande.lignes:
        if ligne.section_karlia == 1 or ligne.destination == DESTINATION_INTITULE:
            continue
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
            description=f"Facturation prestation - {commande.reference_devis}",
            id_opportunity=commande.karlia_opportunity_id,
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
