"""
Service de calcul de révision annuelle des contrats.
Chaque famille de contrat a sa propre règle de révision.

Formule Syntec pour facturer l'année N :
  - indice_ref  = indice mois M de l'année N-2
  - indice_new  = indice mois M de l'année N-1
  - taux        = indice_new / indice_ref
  - montant_N   = montant_N-1 × taux

Exemple facturation 2026 (Syntec Août) :
  - indice_ref  = Août 2024
  - indice_new  = Août 2025
  - taux        = Août2025 / Août2024
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from typing import Optional, Dict
from sqlalchemy.orm import Session
from app.models.models import IndiceRevision, PlanFacturation, Contrat

# ─────────────────────────────────────────────
# Familles de contrats et leurs règles
# ─────────────────────────────────────────────

FAMILLES_CONTRAT = [
    {"code": "COSOLUCE",       "label": "Cosoluce",               "revision": "SYNTEC_AOUT",    "description": "Révision annuelle Syntec Août"},
    {"code": "CANTINE",        "label": "Cantine de France",      "revision": "SYNTEC_OCTOBRE", "description": "Révision annuelle Syntec Octobre"},
    {"code": "DIGITECH",       "label": "Digitech",               "revision": "MANUELLE",       "description": "Révision manuelle par l'utilisateur"},
    {"code": "MAINTENANCE",    "label": "Maintenance matériel",   "revision": "SYNTEC_AOUT",    "description": "Révision annuelle Syntec Août"},
    {"code": "ASSISTANCE_TEL", "label": "Assistance Téléphonique","revision": "SYNTEC_AOUT",    "description": "Révision annuelle Syntec Août"},
    {"code": "KIWI_BACKUP",    "label": "Kiwi Backup",            "revision": "AUCUNE",         "description": "Prix fixe — pas de révision"},
    {"code": "AUTRE",          "label": "Autre",                  "revision": "AUCUNE",         "description": "Prix fixe — pas de révision"},
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
    
    Pour facturer l'année N, on a besoin de :
      - indice_ref : mois M de l'année N-2  (ex: Août 2024 pour 2026)
      - indice_new : mois M de l'année N-1  (ex: Août 2025 pour 2026)

    Retourne {"ok": True, "indice_ref": ..., "indice_new": ...}
          ou {"ok": False, "message": "..."}
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

    # CORRECTION : N-2 et N-1 (pas N-1 et N)
    annee_ref = annee_facturation - 2   # ex: 2024 pour facturer 2026
    annee_new = annee_facturation - 1   # ex: 2025 pour facturer 2026

    indice_ref = get_indice(db, annee_ref, mois)
    indice_new = get_indice(db, annee_new, mois)

    if not indice_ref:
        return {"ok": False, "message": f"Indice Syntec {mois} {annee_ref} manquant"}
    if not indice_new:
        return {"ok": False, "message": f"Indice Syntec {mois} {annee_new} manquant"}

    return {
        "ok": True,
        "indice_ref": indice_ref,   # année N-2
        "indice_new": indice_new,   # année N-1
    }


def calculer_revision(
    db: Session,
    famille: str,
    annee_facturation: int,
    montant_precedent: Decimal,
    nouveau_montant_manuel: Optional[Decimal] = None,
) -> Dict:
    """
    Calcule le montant révisé pour une année de facturation.

    Pour l'année N :
      taux = indice(N-1) / indice(N-2)
      montant_N = montant_N-1 × taux

    Retourne dict avec montant_revise, taux_revision, indice_ref, indice_new, message.
    """
    regle = get_regle_revision(famille)

    # Kiwi Backup — prix fixe
    if regle == "AUCUNE":
        return {
            "ok": True,
            "montant_revise": montant_precedent,
            "taux_revision": Decimal("1.000000"),
            "message": "Prix fixe — pas de révision",
            "indice_ref": None,
            "indice_new": None,
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
            "indice_ref": None,
            "indice_new": None,
        }

    # Révision Syntec automatique
    mois = "AOUT" if regle == "SYNTEC_AOUT" else "OCTOBRE"
    verification = verifier_indices_disponibles(db, famille, annee_facturation)
    if not verification["ok"]:
        return {"ok": False, "message": verification["message"]}

    indice_ref = verification["indice_ref"]   # N-2
    indice_new = verification["indice_new"]   # N-1

    taux = (indice_new.valeur / indice_ref.valeur).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    montant_revise = (montant_precedent * taux).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    annee_ref = annee_facturation - 2
    annee_new = annee_facturation - 1

    return {
        "ok": True,
        "montant_revise": montant_revise,
        "taux_revision": taux,
        "message": f"Syntec {mois}: {annee_ref}({indice_ref.valeur}) → {annee_new}({indice_new.valeur}) = ×{taux}",
        "indice_ref": indice_ref,
        "indice_new": indice_new,
    }
