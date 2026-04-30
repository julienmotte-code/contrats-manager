"""
API Chorus Pro — Gestion des transmissions de factures
"""
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
from app.services.karlia_service import karlia, KarliaError
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chorus", tags=["Chorus Pro"])


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
    code_service_destinataire: Optional[str] = None
    dry_run: bool = False


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
    current_user: dict = Depends(get_current_user)
):
    """Teste la connexion à Chorus Pro."""
    service = _get_chorus_service(db)
    result = await service.tester_connexion()
    return result


@router.post("/auto-config")
async def auto_config_chorus(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
):
    """
    Récupère idUtilisateurCourant et idFournisseur depuis Chorus Pro et les sauvegarde.
    À appeler une fois après configuration des credentials OAuth.
    """
    service = _get_chorus_service(db)
    try:
        info = await service.recuperer_utilisateur_courant()
    except ChorusError as e:
        raise HTTPException(status_code=502, detail={"message": str(e), "detail": e.detail})

    id_utilisateur = info.get("idUtilisateurCourant")
    structure = info.get("structureCourante") or {}
    id_structure = structure.get("idStructureCPP") or structure.get("idStructure")

    if not id_utilisateur or not id_structure:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Réponse Chorus Pro inattendue : idUtilisateurCourant ou idStructureCPP absent.",
                "raw": info,
            }
        )

    saved = {}
    for cle, valeur in [
        ("chorus_id_fournisseur", str(id_structure)),
        ("chorus_id_utilisateur_courant", str(id_utilisateur)),
    ]:
        param = db.query(Parametre).filter(Parametre.cle == cle).first()
        if param:
            param.valeur = valeur
        else:
            db.add(Parametre(cle=cle, valeur=valeur, description=""))
        saved[cle] = valeur
    db.commit()

    return {
        "message": "Auto-configuration Chorus Pro effectuée",
        "saved": saved,
        "structure": structure,
    }


@router.post("/synchro-factures", response_model=SynchroFacturesResponse)
async def synchroniser_factures_karlia(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
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
        # Récupérer les factures depuis Karlia (type 4 = Facture, statut 1 = Acceptée)
        result = await karlia._get("/documents", {
            "type": 4,
            "status": 1,
            "limit": 500,
            "order": "date",
            "direction": "DESC"
        })

        factures_karlia = result.get("data", [])
        logger.info(f"Récupération brute de {len(factures_karlia)} documents depuis Karlia")

        factures_karlia = [
            fk for fk in factures_karlia
            if str(fk.get("id_type")) == "4" and str(fk.get("canceled", "0")) == "0"
        ]
        logger.info(f"Factures Karlia retenues après filtre: {len(factures_karlia)}")

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
                client_id = fk.get("id_customer") or fk.get("id_customer_supplier")
                client_nom = fk.get("customer_name") or fk.get("customer_supplier_title", "")
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
                montant_ht = Decimal(str(fk.get("total_without_tax", 0) or 0))
                montant_ttc = Decimal(str(fk.get("total_with_tax", 0) or 0))
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
                        numero_facture=fk.get("number") or fk.get("reference") or f"FAC-{karlia_id}",
                        reference=fk.get("reference") or fk.get("number"),
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
    current_user: dict = Depends(get_current_user)
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
    current_user: dict = Depends(get_current_user)
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
    current_user: dict = Depends(get_current_user)
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
    current_user: dict = Depends(get_current_user)
):
    """
    Transmet une ou plusieurs factures vers Chorus Pro.
    """
    service = _get_chorus_service(db)

    resultats = []
    for fid in request.facture_ids:
        facture = db.query(FactureKarlia).filter(FactureKarlia.id == fid).first()
        if not facture:
            resultats.append({"facture_id": fid, "succes": False, "erreur": "Facture non trouvée"})
            continue

        if facture.statut_chorus in ("TRANSMISE", "ACCEPTEE", "EN_COURS"):
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

        if request.dry_run:
            try:
                reponse = await service.soumettre_facture(
                    destinataire_siret=facture.client_siret,
                    destinataire_code_service=request.code_service_destinataire or facture.client_code_service,
                    numero_facture=facture.numero_facture,
                    date_facture=facture.date_facture,
                    date_echeance=facture.date_echeance,
                    montant_ht=facture.montant_ht,
                    montant_tva=facture.montant_tva or Decimal("0"),
                    montant_ttc=facture.montant_ttc or facture.montant_ht,
                    commentaire=f"Facture {facture.numero_facture}",
                    dry_run=True,
                )
                resultats.append({
                    "facture_id": fid,
                    "succes": True,
                    "dry_run": True,
                    "payload": reponse.get("payload"),
                })
            except ChorusError as e:
                resultats.append({
                    "facture_id": fid,
                    "succes": False,
                    "dry_run": True,
                    "erreur": str(e),
                })
            continue

        # Créer l'enregistrement de transmission
        transmission = TransmissionChorus(
            facture_id=facture.id,
            statut="EN_COURS",
            transmis_par=getattr(current_user, "login", None) or getattr(current_user, "email", None) or "system",
            transmis_at=datetime.now()
        )
        db.add(transmission)
        facture.statut_chorus = "EN_COURS"
        db.commit()

        try:
            reponse = await service.soumettre_facture(
                destinataire_siret=facture.client_siret,
                destinataire_code_service=request.code_service_destinataire or facture.client_code_service,
                numero_facture=facture.numero_facture,
                date_facture=facture.date_facture,
                date_echeance=facture.date_echeance,
                montant_ht=facture.montant_ht,
                montant_tva=facture.montant_tva or Decimal("0"),
                montant_ttc=facture.montant_ttc or facture.montant_ht,
                commentaire=f"Facture {facture.numero_facture}"
            )

            id_flux = reponse.get("numeroFluxDepot") or reponse.get("idFlux")
            id_facture = reponse.get("identifiantFactureCPP") or reponse.get("idFacture")

            transmission.statut = "SUCCES"
            transmission.chorus_id_flux = str(id_flux) if id_flux else None
            transmission.chorus_id_facture = str(id_facture) if id_facture else None
            transmission.payload_json = service.last_request
            transmission.reponse_json = service.last_response or reponse

            facture.statut_chorus = "TRANSMISE"
            facture.date_transmission = datetime.now()
            facture.chorus_numero_flux = str(id_flux) if id_flux else None
            facture.chorus_message_erreur = None

            if facture.karlia_document_id:
                try:
                    await karlia.marquer_facture_envoyee(str(facture.karlia_document_id))
                except Exception as e:
                    logger.error(f"Erreur mise à jour statut Karlia facture {facture.karlia_document_id}: {e}")

            db.commit()

            resultats.append({
                "facture_id": fid,
                "succes": True,
                "numero_flux": id_flux,
                "id_facture_chorus": id_facture
            })

        except ChorusError as e:
            transmission.statut = "ECHEC"
            transmission.code_retour = str(e.status_code)
            transmission.message_retour = e.message
            transmission.payload_json = service.last_request
            transmission.reponse_json = service.last_response or e.detail

            facture.statut_chorus = "ERREUR"
            facture.chorus_message_erreur = f"{e.status_code}: {e.message}"

            db.commit()

            resultats.append({
                "facture_id": fid,
                "succes": False,
                "erreur": str(e),
                "detail": e.detail
            })

        except Exception as e:
            transmission.statut = "ECHEC"
            transmission.message_retour = str(e)
            transmission.payload_json = service.last_request
            transmission.reponse_json = service.last_response

            facture.statut_chorus = "ERREUR"
            facture.chorus_message_erreur = str(e)

            db.commit()

            resultats.append({
                "facture_id": fid,
                "succes": False,
                "erreur": str(e)
            })

    # Résumé
    nb_succes = sum(1 for r in resultats if r.get("succes"))
    nb_echecs = len(resultats) - nb_succes

    return {
        "transmises": nb_succes,
        "echecs": nb_echecs,
        "details": resultats
    }


@router.get("/factures/{facture_id}/transmissions", response_model=List[TransmissionOut])
async def historique_transmissions(
    facture_id: str,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user)
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
    current_user: dict = Depends(get_current_user)
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
    current_user: dict = Depends(get_current_user)
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
