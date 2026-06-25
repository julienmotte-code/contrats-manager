from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_role
from app.services import ca_service, ca_marges_service, ca_recurrent_service, ca_recap_service, recap_marges_service

router = APIRouter(prefix="/api/ca", tags=["ca"])


@router.get("/comparatif")
def comparatif(
    date_debut: date = Query(...),
    date_fin: date = Query(...),
    n: int = Query(5, ge=1, le=15),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    if date_fin < date_debut:
        raise HTTPException(status_code=400, detail="date_fin anterieure a date_debut")
    return ca_service.calculer_comparatif(db, date_debut, date_fin, n)


@router.post("/rafraichir-karlia")
def rafraichir_karlia(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    try:
        return ca_service.rafraichir_karlia(db)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/comparatif-refresh")
def comparatif_refresh(
    date_debut: date = Query(...),
    date_fin: date = Query(...),
    n: int = Query(5, ge=1, le=15),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    if date_fin < date_debut:
        raise HTTPException(status_code=400, detail="date_fin anterieure a date_debut")
    try:
        refresh = ca_service.rafraichir_karlia(db)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    resultat = ca_service.calculer_comparatif(db, date_debut, date_fin, n)
    resultat["refresh"] = refresh
    return resultat


# ── CA & marge par type de prestation (greffe niveau ligne, cf. ca_marges_service) ──
# Le fetch detail N+1 (~72 s) est intenable en synchrone derriere Cloudflare (524).
# Refresh = tache de fond + polling : le GET ne bloque JAMAIS sur Karlia.

@router.get("/marges-par-prestation")
def marges_par_prestation(
    exercice: int = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    """Agregat CA/marge par categorie (cache local) — instantane, ne bloque jamais.
    Si le miroir est vide ou perime, declenche un refresh de FOND (fire-and-forget) et
    renvoie son etat dans `refresh` ; le front pollera /refresh-status."""
    resultat = ca_marges_service.agreger_marges(db, exercice)
    etat_data = ca_marges_service.etat_donnees(db)
    if etat_data["vide"] or etat_data["perime"]:
        resultat["refresh"] = ca_marges_service.demarrer_refresh_async()
    else:
        resultat["refresh"] = {"etat": "idle"}
    return resultat


@router.post("/marges-par-prestation/rafraichir", status_code=202)
def marges_par_prestation_rafraichir(
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    """Declenche le refresh complet en tache de fond (idempotent) et rend la main
    immediatement (202). Le front suit l'avancement via /refresh-status."""
    return ca_marges_service.demarrer_refresh_async()


@router.get("/marges-par-prestation/refresh-status")
def marges_par_prestation_refresh_status(
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    """Etat courant de la tache de fond (polling) : idle | en_cours | termine | erreur."""
    return ca_marges_service.get_refresh_state()


# ── CA recurrent par famille de contrat (source plan_facturation, lecture pure) ──

@router.get("/recurrent-par-famille")
def recurrent_par_famille(
    annee: int = Query(...),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    """CA recurrent contractuel de l'annee (plan_facturation.montant_ht_prevu) groupe par
    famille de contrat. Lecture DB pure, instantane (aucun refresh Karlia)."""
    return ca_recurrent_service.agreger_recurrent(db, annee)


# ── Recapitulatif marge brute importe des Excel historiques (lecture DB pure) ──

@router.get("/recap-excel/annees")
def recap_excel_annees(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    """Annees disponibles dans le recapitulatif Excel importe (desc)."""
    return {"annees": ca_recap_service.annees_disponibles(db)}


@router.get("/recap-excel")
def recap_excel(
    annee: int = Query(...),
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE", "DIRECTION")),
):
    """Recapitulatif marge brute d'une annee : familles x 12 mois + totaux.
    Source FUSIONNEE = Excel (<=9002) + prolongement Karlia (numero_int>9002). Meme
    schema que l'Excel seul : le front est inchange."""
    return recap_marges_service.get_recap_fusionne(db, annee)
