"""
API Chorus Pro — Gestion des transmissions de factures
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from typing import List, Optional
from datetime import datetime, date
from decimal import Decimal
from pydantic import BaseModel
import logging

from app.core.database import get_db
from app.models.models import (
    FactureKarlia, TransmissionChorus, Parametre, ClientCache
)
from app.services.chorus_service import ChorusProService, ChorusError, get_chorus_service_from_params
from app.services.chorus_flux_service import ChorusFluxService, DepotFluxResult
from app.services.facturx_orchestrator import (
    build_facturx_for_karlia_document,
    FacturxOrchestrationError,
)
from app.services.karlia_service import karlia, KarliaError
from app.core.security import require_role

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chorus", tags=["Chorus Pro"])


# Délai inter-facture en secondes : évite de marteler l'API Chorus quand on
# transmet en lot. Volontairement court (compatible avec nginx 60s pour
# quelques factures), pas conçu pour gros volumes — voir note dans
# transmettre_factures pour le passage en tâche de fond.
DELAI_INTER_FACTURE_SEC = 0.7


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMAS
# ══════════════════════════════════════════════════════════════════════════════

class FactureKarliaOut(BaseModel):
    id: str
    karlia_document_id: int
    numero_facture: str
    reference: Optional[str] = None
    client_karlia_id: int
    client_nom: Optional[str] = None
    client_siret: Optional[str] = None
    client_code_service: Optional[str] = None
    montant_ht: float
    montant_tva: Optional[float] = None
    montant_ttc: Optional[float] = None
    date_facture: date
    date_echeance: Optional[date] = None
    statut_chorus: str
    date_transmission: Optional[datetime] = None
    chorus_numero_flux: Optional[str] = None
    chorus_statut_technique: Optional[str] = None
    chorus_message_erreur: Optional[str] = None
    contrat_id: Optional[str] = None
    imported_at: datetime

    class Config:
        from_attributes = True


class TransmissionOut(BaseModel):
    id: str
    facture_id: str
    chorus_id_flux: Optional[str] = None
    chorus_id_facture: Optional[str] = None
    statut: str
    code_retour: Optional[str] = None
    message_retour: Optional[str] = None
    transmis_par: Optional[str] = None
    transmis_at: datetime

    class Config:
        from_attributes = True


class TransmettreRequest(BaseModel):
    facture_ids: List[str]
    # Champ historique conservé pour compat front. Ignoré par la voie flux :
    # la référence acheteur (BT-10) est gérée dans le XML CII embarqué, et
    # on a fait le choix d'omettre BT-10 (valeur Karlia non fiable).
    code_service_destinataire: Optional[str] = None


class SynchroFacturesResponse(BaseModel):
    importees: int
    mises_a_jour: int
    erreurs: int
    message: str


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _get_chorus_params(db: Session) -> dict:
    """Récupère tous les paramètres Chorus Pro."""
    params = db.query(Parametre).filter(Parametre.cle.like("chorus_%")).all()
    return {p.cle: p.valeur for p in params}


def _get_chorus_service(db: Session) -> ChorusProService:
    """Instancie le service Chorus Pro avec les params de la base."""
    params = _get_chorus_params(db)
    service = get_chorus_service_from_params(params)
    if not service:
        raise HTTPException(
            status_code=400,
            detail="Configuration Chorus Pro incomplète. Vérifiez les paramètres dans l'écran Paramètres."
        )
    return service


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/test-connexion")
async def tester_connexion_chorus(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """Teste la connexion à Chorus Pro."""
    service = _get_chorus_service(db)
    result = await service.tester_connexion()
    return result


@router.post("/synchro-factures", response_model=SynchroFacturesResponse)
async def synchroniser_factures_karlia(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """
    Synchronise les factures depuis Karlia vers la table locale.
    Récupère les factures émises (type 4 = Facture) non encore importées.
    """
    # Utiliser l'instance globale karlia
    importees = 0
    mises_a_jour = 0
    erreurs = 0

    try:
        # Récupérer les factures depuis Karlia (type 4 = Facture, statut 2 = Envoyée)
        result = await karlia._get("/documents", {
            "type": 4,
            "status": 2,
            "limit": 500,
            "order": "date",
            "direction": "DESC"
        })

        factures_karlia = result.get("data", [])
        logger.info(f"Récupération de {len(factures_karlia)} factures depuis Karlia")

        for fk in factures_karlia:
            try:
                karlia_id = fk.get("id")
                if not karlia_id:
                    continue

                # Vérifier si déjà importée
                existante = db.query(FactureKarlia).filter(
                    FactureKarlia.karlia_document_id == karlia_id
                ).first()

                # Récupérer les infos client
                client_id = fk.get("id_customer")
                client_nom = fk.get("customer_name", "")
                client_siret = None

                # Chercher le SIRET dans le cache client
                if client_id:
                    client_cache = db.query(ClientCache).filter(
                        ClientCache.karlia_id == str(client_id)
                    ).first()
                    if client_cache:
                        client_siret = client_cache.siret
                        client_nom = client_cache.nom

                # Calculer les montants
                montant_ht = Decimal(str(fk.get("amount_without_tax", 0) or 0))
                montant_ttc = Decimal(str(fk.get("amount_with_tax", 0) or 0))
                montant_tva = montant_ttc - montant_ht

                # Parser les dates
                date_facture = None
                if fk.get("date"):
                    try:
                        date_facture = datetime.strptime(fk["date"], "%d/%m/%Y").date()
                    except ValueError:
                        date_facture = date.today()

                date_echeance = None
                if fk.get("date_end"):
                    try:
                        date_echeance = datetime.strptime(fk["date_end"], "%d/%m/%Y").date()
                    except ValueError:
                        pass

                if existante:
                    # Mise à jour si pas encore transmise
                    if existante.statut_chorus == "NON_TRANSMISE":
                        existante.client_nom = client_nom
                        existante.client_siret = client_siret
                        existante.montant_ht = montant_ht
                        existante.montant_tva = montant_tva
                        existante.montant_ttc = montant_ttc
                        existante.date_echeance = date_echeance
                        existante.updated_at = datetime.now()
                        mises_a_jour += 1
                else:
                    # Nouvelle facture
                    nouvelle = FactureKarlia(
                        karlia_document_id=karlia_id,
                        numero_facture=fk.get("reference", f"FAC-{karlia_id}"),
                        reference=fk.get("reference"),
                        client_karlia_id=client_id or 0,
                        client_nom=client_nom,
                        client_siret=client_siret,
                        montant_ht=montant_ht,
                        montant_tva=montant_tva,
                        montant_ttc=montant_ttc,
                        date_facture=date_facture or date.today(),
                        date_echeance=date_echeance,
                        statut_chorus="NON_TRANSMISE"
                    )
                    db.add(nouvelle)
                    importees += 1

            except Exception as e:
                logger.error(f"Erreur import facture {fk.get('id')}: {e}")
                erreurs += 1

        db.commit()

    except Exception as e:
        logger.error(f"Erreur synchronisation factures: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    return SynchroFacturesResponse(
        importees=importees,
        mises_a_jour=mises_a_jour,
        erreurs=erreurs,
        message=f"Synchronisation terminée : {importees} importées, {mises_a_jour} mises à jour, {erreurs} erreurs"
    )


@router.get("/factures", response_model=List[FactureKarliaOut])
async def lister_factures(
    statut: Optional[str] = Query(None, description="Filtrer par statut Chorus"),
    date_debut: Optional[date] = Query(None),
    date_fin: Optional[date] = Query(None),
    search: Optional[str] = Query(None, description="Recherche par numéro ou client"),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """Liste les factures avec filtres."""
    query = db.query(FactureKarlia)

    if statut:
        query = query.filter(FactureKarlia.statut_chorus == statut)
    if date_debut:
        query = query.filter(FactureKarlia.date_facture >= date_debut)
    if date_fin:
        query = query.filter(FactureKarlia.date_facture <= date_fin)
    if search:
        search_pattern = f"%{search}%"
        query = query.filter(
            (FactureKarlia.numero_facture.ilike(search_pattern)) |
            (FactureKarlia.client_nom.ilike(search_pattern))
        )

    factures = query.order_by(desc(FactureKarlia.date_facture)).limit(500).all()

    return [
        FactureKarliaOut(
            id=str(f.id),
            karlia_document_id=f.karlia_document_id,
            numero_facture=f.numero_facture,
            reference=f.reference,
            client_karlia_id=f.client_karlia_id,
            client_nom=f.client_nom,
            client_siret=f.client_siret,
            client_code_service=f.client_code_service,
            montant_ht=float(f.montant_ht) if f.montant_ht else 0,
            montant_tva=float(f.montant_tva) if f.montant_tva else 0,
            montant_ttc=float(f.montant_ttc) if f.montant_ttc else 0,
            date_facture=f.date_facture,
            date_echeance=f.date_echeance,
            statut_chorus=f.statut_chorus,
            date_transmission=f.date_transmission,
            chorus_numero_flux=f.chorus_numero_flux,
            chorus_statut_technique=f.chorus_statut_technique,
            chorus_message_erreur=f.chorus_message_erreur,
            contrat_id=str(f.contrat_id) if f.contrat_id else None,
            imported_at=f.imported_at
        )
        for f in factures
    ]


@router.get("/factures/{facture_id}", response_model=FactureKarliaOut)
async def obtenir_facture(
    facture_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """Détail d'une facture."""
    facture = db.query(FactureKarlia).filter(FactureKarlia.id == facture_id).first()
    if not facture:
        raise HTTPException(status_code=404, detail="Facture non trouvée")

    return FactureKarliaOut(
        id=str(facture.id),
        karlia_document_id=facture.karlia_document_id,
        numero_facture=facture.numero_facture,
        reference=facture.reference,
        client_karlia_id=facture.client_karlia_id,
        client_nom=facture.client_nom,
        client_siret=facture.client_siret,
        client_code_service=facture.client_code_service,
        montant_ht=float(facture.montant_ht) if facture.montant_ht else 0,
        montant_tva=float(facture.montant_tva) if facture.montant_tva else 0,
        montant_ttc=float(facture.montant_ttc) if facture.montant_ttc else 0,
        date_facture=facture.date_facture,
        date_echeance=facture.date_echeance,
        statut_chorus=facture.statut_chorus,
        date_transmission=facture.date_transmission,
        chorus_numero_flux=facture.chorus_numero_flux,
        chorus_statut_technique=facture.chorus_statut_technique,
        chorus_message_erreur=facture.chorus_message_erreur,
        contrat_id=str(facture.contrat_id) if facture.contrat_id else None,
        imported_at=facture.imported_at
    )


@router.put("/factures/{facture_id}/siret")
async def mettre_a_jour_siret(
    facture_id: str,
    siret: str = Query(..., min_length=14, max_length=14),
    code_service: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """Met à jour le SIRET destinataire d'une facture."""
    facture = db.query(FactureKarlia).filter(FactureKarlia.id == facture_id).first()
    if not facture:
        raise HTTPException(status_code=404, detail="Facture non trouvée")

    if facture.statut_chorus not in ("NON_TRANSMISE", "ERREUR", "REJETEE"):
        raise HTTPException(status_code=400, detail="Cette facture ne peut plus être modifiée")

    facture.client_siret = siret
    facture.client_code_service = code_service
    facture.updated_at = datetime.now()
    db.commit()

    return {"message": "SIRET mis à jour", "siret": siret, "code_service": code_service}


@router.post("/transmettre")
async def transmettre_factures(
    request: TransmettreRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """
    Transmet une ou plusieurs factures vers Chorus Pro via la voie
    'dépôt de flux' Factur-X.

    Pipeline par facture (indépendant — l'échec d'une n'arrête pas les autres) :
        1. Charger FactureKarlia + valider SIRET destinataire.
        2. Générer le Factur-X (PDF/A-3 + XML CII embarqué) via
           build_facturx_for_karlia_document.
        3. Déposer sur /deposer/flux (syntaxe IN_DP_E2_CII_FACTURX).
        4. Sur succès (codeRetour=0 + numeroFluxDepot) : statut_chorus =
           "TRANSMISE", numéro de flux et date de transmission stockés.
        5. Sur échec : statut_chorus = "ERREUR", message d'erreur stocké.
        6. db.commit() par facture, trace dans TransmissionChorus à chaque
           tentative, délai court entre factures.

    Garde anti-doublon : on bloque seulement les factures déjà acceptées côté
    Chorus ("TRANSMISE" ou "ACCEPTEE"). "EN_COURS" n'est PAS bloquant : un
    EN_COURS sans dépôt abouti est un verrou orphelin (crash entre commit du
    verrou et résultat) — il doit être relançable depuis le module, pas en
    SQL manuel. "ERREUR" est également relançable (retry après correction).

    Robustesse du verrou : toutes les branches d'exception et la branche
    "codeRetour ≠ 0" font transitionner statut_chorus de EN_COURS vers
    ERREUR avec db.commit() avant de passer à la facture suivante. Le seul
    cas résiduel de blocage est un crash brutal (kill -9, OOM) entre le
    commit du verrou et le résultat — récupérable via relance grâce à la
    règle ci-dessus.

    Limites actuelles :
        - Synchrone : la requête HTTP frontend attend la fin de la boucle.
          Avec nginx en proxy (timeout 60s), au-delà de ~10-15 factures le
          frontend recevra un 504 même si le backend continue. Le multi-
          facture massif devra basculer en tâche de fond (Celery / asyncio
          task / endpoint de polling) dans une itération ultérieure.
        - Pas de suivi post-dépôt : on stocke "TRANSMISE" dès que Chorus a
          accepté le flux, mais le statut d'intégration réel (IN_INTEGRE /
          IN_REJETE) requiert un POST /consulter/compteRendu différé, qui
          sera exposé dans un endpoint séparé.
    """
    service = _get_chorus_service(db)
    flux_svc = ChorusFluxService(service)
    is_test = bool(service.mode_qualification)

    resultats = []
    for fid in request.facture_ids:
        facture = db.query(FactureKarlia).filter(FactureKarlia.id == fid).first()
        if not facture:
            resultats.append({"facture_id": fid, "succes": False, "erreur": "Facture non trouvée"})
            continue

        # Seuls TRANSMISE et ACCEPTEE bloquent un nouvel envoi.
        # EN_COURS est relançable (verrou orphelin possible), voir docstring.
        if facture.statut_chorus in ("TRANSMISE", "ACCEPTEE"):
            resultats.append({
                "facture_id": fid,
                "succes": False,
                "erreur": f"Facture déjà transmise (statut: {facture.statut_chorus})"
            })
            continue

        if not facture.client_siret:
            resultats.append({
                "facture_id": fid,
                "succes": False,
                "erreur": "SIRET du destinataire manquant"
            })
            continue

        # Relance d'un EN_COURS orphelin : on logge explicitement pour ne
        # pas masquer le fait qu'on écrase un verrou laissé par une
        # tentative précédente.
        if facture.statut_chorus == "EN_COURS":
            logger.warning(
                "Chorus transmettre: relance d'une facture en EN_COURS "
                "(verrou orphelin probable) facture=%r",
                facture.numero_facture,
            )

        # Trace + verrou logique côté facture (EN_COURS) commité immédiatement
        # pour ne pas laisser de fantôme si le process tombe pendant le dépôt.
        transmission = TransmissionChorus(
            facture_id=facture.id,
            statut="EN_COURS",
            transmis_par=current_user.login,
            transmis_at=datetime.now(),
            is_test=is_test,
        )
        db.add(transmission)
        facture.statut_chorus = "EN_COURS"
        db.commit()

        try:
            # 1) Génération Factur-X (PDF/A-3 + XML CII)
            logger.info(
                "Chorus transmettre: début Factur-X facture=%r karlia_doc_id=%s",
                facture.numero_facture, facture.karlia_document_id,
            )
            facturx_result = await build_facturx_for_karlia_document(
                db, facture.karlia_document_id
            )
            pdf_bytes = facturx_result.pdf_facturx_bytes
            nom_fichier = f"{facture.numero_facture}.pdf"

            # 2) Dépôt /deposer/flux
            depot: DepotFluxResult = await flux_svc.deposer_flux(pdf_bytes, nom_fichier)

            # 3) Évaluation du résultat. Chorus Pro renvoie codeRetour=0
            # quand le dépôt est accepté ; un numeroFluxDepot non-nul est
            # le marqueur de référence pour le suivi ultérieur.
            depot_ok = (depot.code_retour == 0 and bool(depot.numero_flux_depot))

            # 4) Logging traçabilité (réponse complète) — premier dépôt réel
            logger.info(
                "Chorus transmettre: dépôt %s facture=%r numeroFluxDepot=%s "
                "codeRetour=%s libelle=%r dateDepot=%s raw=%s",
                "OK" if depot_ok else "KO",
                facture.numero_facture,
                depot.numero_flux_depot,
                depot.code_retour,
                depot.libelle,
                depot.date_depot,
                depot.raw,
            )

            if depot_ok:
                facture.statut_chorus = "TRANSMISE"
                facture.chorus_numero_flux = depot.numero_flux_depot
                facture.date_transmission = datetime.now()
                facture.chorus_message_erreur = None

                transmission.statut = "SUCCES"
                transmission.chorus_id_flux = depot.numero_flux_depot
                transmission.code_retour = str(depot.code_retour) if depot.code_retour is not None else None
                transmission.message_retour = depot.libelle
                transmission.reponse_json = depot.raw

                db.commit()
                resultats.append({
                    "facture_id": fid,
                    "succes": True,
                    "numero_flux": depot.numero_flux_depot,
                    "date_depot": depot.date_depot,
                    "code_retour": depot.code_retour,
                    "libelle": depot.libelle,
                })
            else:
                # codeRetour ≠ 0 ou numéro de flux absent : Chorus a répondu
                # mais n'a pas pris en compte le dépôt. On stocke la réponse
                # brute pour analyse hors-ligne.
                err_msg = (
                    f"codeRetour={depot.code_retour}, "
                    f"libelle={depot.libelle!r}, "
                    f"numeroFluxDepot={depot.numero_flux_depot!r}"
                )
                facture.statut_chorus = "ERREUR"
                facture.chorus_message_erreur = err_msg

                transmission.statut = "ECHEC"
                transmission.code_retour = str(depot.code_retour) if depot.code_retour is not None else None
                transmission.message_retour = depot.libelle or err_msg
                transmission.reponse_json = depot.raw

                db.commit()
                resultats.append({
                    "facture_id": fid,
                    "succes": False,
                    "erreur": err_msg,
                    "detail": depot.raw,
                })

        except FacturxOrchestrationError as e:
            # Erreur de génération Factur-X (paramètre manquant, document
            # Karlia absent, etc.) — pas un échec Chorus, mais bloque le dépôt.
            logger.error(
                "Chorus transmettre: échec génération Factur-X facture=%r : %s",
                facture.numero_facture, e,
            )
            facture.statut_chorus = "ERREUR"
            facture.chorus_message_erreur = f"Génération Factur-X impossible : {e}"

            transmission.statut = "ECHEC"
            transmission.message_retour = f"Génération Factur-X impossible : {e}"

            db.commit()
            resultats.append({
                "facture_id": fid,
                "succes": False,
                "erreur": f"Génération Factur-X impossible : {e}",
            })

        except ChorusError as e:
            logger.error(
                "Chorus transmettre: ChorusError facture=%r status=%s msg=%s detail=%s",
                facture.numero_facture, e.status_code, e.message, e.detail,
            )
            facture.statut_chorus = "ERREUR"
            facture.chorus_message_erreur = f"{e.status_code}: {e.message}"

            transmission.statut = "ECHEC"
            transmission.code_retour = str(e.status_code)
            transmission.message_retour = e.message
            transmission.reponse_json = e.detail

            db.commit()
            resultats.append({
                "facture_id": fid,
                "succes": False,
                "erreur": str(e),
                "detail": e.detail,
            })

        except Exception as e:
            logger.exception(
                "Chorus transmettre: exception inattendue facture=%r",
                facture.numero_facture,
            )
            facture.statut_chorus = "ERREUR"
            facture.chorus_message_erreur = str(e)

            transmission.statut = "ECHEC"
            transmission.message_retour = str(e)

            db.commit()
            resultats.append({
                "facture_id": fid,
                "succes": False,
                "erreur": str(e),
            })

        # Délai inter-facture (évite de marteler l'API Chorus).
        await asyncio.sleep(DELAI_INTER_FACTURE_SEC)

    # Résumé
    nb_succes = sum(1 for r in resultats if r.get("succes"))
    nb_echecs = len(resultats) - nb_succes

    return {
        "transmises": nb_succes,
        "echecs": nb_echecs,
        "details": resultats,
    }


@router.get("/factures/{facture_id}/transmissions", response_model=List[TransmissionOut])
async def historique_transmissions(
    facture_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """Historique des tentatives de transmission pour une facture."""
    transmissions = db.query(TransmissionChorus).filter(
        TransmissionChorus.facture_id == facture_id
    ).order_by(desc(TransmissionChorus.transmis_at)).all()

    return [
        TransmissionOut(
            id=str(t.id),
            facture_id=str(t.facture_id),
            chorus_id_flux=t.chorus_id_flux,
            chorus_id_facture=t.chorus_id_facture,
            statut=t.statut,
            code_retour=t.code_retour,
            message_retour=t.message_retour,
            transmis_par=t.transmis_par,
            transmis_at=t.transmis_at
        )
        for t in transmissions
    ]


@router.post("/rechercher-structure")
async def rechercher_structure(
    siret: str = Query(..., min_length=14, max_length=14),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """Recherche une structure dans Chorus Pro par SIRET."""
    service = _get_chorus_service(db)

    try:
        result = await service.rechercher_structure_destinataire(siret)
        return result
    except ChorusError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/statistiques")
async def statistiques_chorus(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE"))
):
    """Statistiques des transmissions Chorus Pro."""
    stats = db.query(
        FactureKarlia.statut_chorus,
        func.count(FactureKarlia.id).label("count"),
        func.sum(FactureKarlia.montant_ht).label("montant_total")
    ).group_by(FactureKarlia.statut_chorus).all()

    return {
        "par_statut": [
            {
                "statut": s.statut_chorus,
                "count": s.count,
                "montant_total": float(s.montant_total or 0)
            }
            for s in stats
        ],
        "total_factures": sum(s.count for s in stats),
        "total_ht": sum(float(s.montant_total or 0) for s in stats)
    }
