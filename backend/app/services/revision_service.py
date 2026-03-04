"""
Service de calcul de révision annuelle des contrats.
Chaque famille de contrat a sa propre règle de révision.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional, Dict, Tuple
from sqlalchemy.orm import Session
from app.models.models import IndiceRevision, PlanFacturation, Contrat

# ─────────────────────────────────────────────
# Familles de contrats et leurs règles
# ─────────────────────────────────────────────

FAMILLES_CONTRAT = [
    {"code": "COSOLUCE",        "label": "Cosoluce",              "revision": "SYNTEC_AOUT",    "description": "Révision annuelle Syntec Août"},
    {"code": "CANTINE",         "label": "Cantine de France",     "revision": "SYNTEC_OCTOBRE", "description": "Révision annuelle Syntec Octobre"},
    {"code": "DIGITECH",        "label": "Digitech",              "revision": "MANUELLE",       "description": "Révision manuelle par l'utilisateur"},
    {"code": "MAINTENANCE",     "label": "Maintenance matériel",  "revision": "SYNTEC_AOUT",    "description": "Révision annuelle Syntec Août"},
    {"code": "ASSISTANCE_TEL",  "label": "Assistance Téléphonique","revision": "SYNTEC_AOUT",   "description": "Révision annuelle Syntec Août"},
    {"code": "KIWI_BACKUP",     "label": "Kiwi Backup",           "revision": "AUCUNE",         "description": "Prix fixe — pas de révision"},
]

REVISION_PAR_FAMILLE = {f["code"]: f["revision"] for f in FAMILLES_CONTRAT}

def get_regle_revision(famille_contrat: str) -> str:
    """Retourne la règle de révision pour une famille de contrat."""
    return REVISION_PAR_FAMILLE.get(famille_contrat, "SYNTEC_AOUT")

def get_indice(db: Session, annee: int, mois: str) -> Optional[IndiceRevision]:
    """Récupère l'indice Syntec pour une année et un mois donnés."""
    return db.query(IndiceRevision).filter(
        IndiceRevision.annee == annee,
        IndiceRevision.mois == mois
    ).first()

def verifier_indices_disponibles(db: Session, famille: str, annee_facturation: int) -> Dict:
    """
    Vérifie que les indices nécessaires sont disponibles pour calculer la révision.
    Retourne {"ok": True} ou {"ok": False, "message": "..."}
    """
    regle = get_regle_revision(famille)

    if regle == "AUCUNE":
        return {"ok": True, "message": "Pas de révision"}

    if regle == "MANUELLE":
        return {"ok": True, "message": "Révision manuelle"}

    if regle == "SYNTEC_AOUT":
        mois = "AOUT"
    elif regle == "SYNTEC_OCTOBRE":
        mois = "OCTOBRE"
    else:
        return {"ok": False, "message": f"Règle inconnue: {regle}"}

    annee_n = annee_facturation - 1
    annee_n1 = annee_facturation

    indice_n = get_indice(db, annee_n, mois)
    indice_n1 = get_indice(db, annee_n1, mois)

    if not indice_n:
        return {"ok": False, "message": f"Indice Syntec {mois} {annee_n} manquant"}
    if not indice_n1:
        return {"ok": False, "message": f"Indice Syntec {mois} {annee_n1} manquant"}

    return {"ok": True, "indice_n": indice_n, "indice_n1": indice_n1}

def calculer_revision(
    db: Session,
    famille: str,
    annee_facturation: int,
    montant_precedent: Decimal,
    nouveau_montant_manuel: Optional[Decimal] = None,
) -> Dict:
    """
    Calcule le montant révisé pour une année de facturation.
    Retourne dict avec montant_revise, taux_revision, indice_n, indice_n1, message.
    """
    regle = get_regle_revision(famille)

    # Kiwi Backup — prix fixe
    if regle == "AUCUNE":
        return {
            "ok": True,
            "montant_revise": montant_precedent,
            "taux_revision": Decimal("1.000000"),
            "message": "Prix fixe — pas de révision",
            "indice_n": None,
            "indice_n1": None,
        }

    # Digitech — révision manuelle
    if regle == "MANUELLE":
        if nouveau_montant_manuel is None:
            return {"ok": False, "message": "Montant révisé requis pour les contrats Digitech"}
        taux = (nouveau_montant_manuel / montant_precedent).quantize(Decimal("0.000001")) if montant_precedent else Decimal("1")
        return {
            "ok": True,
            "montant_revise": nouveau_montant_manuel,
            "taux_revision": taux,
            "message": f"Révision manuelle: {montant_precedent} → {nouveau_montant_manuel} €",
            "indice_n": None,
            "indice_n1": None,
        }

    # Révision Syntec automatique
    mois = "AOUT" if regle == "SYNTEC_AOUT" else "OCTOBRE"
    verification = verifier_indices_disponibles(db, famille, annee_facturation)
    if not verification["ok"]:
        return {"ok": False, "message": verification["message"]}

    indice_n = verification["indice_n"]
    indice_n1 = verification["indice_n1"]
    taux = (indice_n1.valeur / indice_n.valeur).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    montant_revise = (montant_precedent * taux).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "ok": True,
        "montant_revise": montant_revise,
        "taux_revision": taux,
        "message": f"Syntec {mois} {annee_facturation-1}({indice_n.valeur}) → {annee_facturation}({indice_n1.valeur}) = ×{taux}",
        "indice_n": indice_n,
        "indice_n1": indice_n1,
    }
