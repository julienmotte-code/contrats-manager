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
from app.models.models import Commande, CommandeLigne, Prestation, Contrat
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

        db.refresh(commande)
        return _commande_to_response(commande)

    # ─── Chemin ancien (global) ─────────────────────────────────────────
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
