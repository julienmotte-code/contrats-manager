"""
Routes API — Tableau de bord
GET /api/dashboard/stats → Statistiques globales pour la page d'accueil
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date
import logging

from app.core.database import get_db
from app.core.security import require_role
from app.models.models import Contrat, Commande

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Libellés des familles de contrats ───────────────────────
FAMILLE_LABELS = {
    "COSOLUCE": "Cosoluce",
    "MAINTENANCE": "Maintenance système",
    "KIWI_BACKUP": "Kiwi Backup",
    "DIGITECH": "Digitech",
    "AUTRE": "Autres",
    "CANTINE": "Cantine de France",
    "ASSISTANCE_TEL": "Assistance téléphonique",
    "DIVERS": "Divers",
}


def _label_famille(code: str) -> str:
    if not code:
        return "Non classé"
    return FAMILLE_LABELS.get(code, code.replace("_", " ").title())


# ── Route principale ────────────────────────────────────────

@router.get("/stats")
def dashboard_stats(
    db: Session = Depends(get_db),
    current_user = Depends(require_role("ADMIN", "GESTIONNAIRE")),
):
    """
    Retourne l'ensemble des statistiques pour la page d'accueil.
    Réservé aux rôles ADMIN et GESTIONNAIRE — les FORMATEUR/TECHNICIEN
    utilisent /api/prestations/formateur/{id} via un dashboard dédié.

    Forme de la réponse :
    {
      "total_contrats": int,
      "ca_annuel_ht": float,
      "a_renouveler_ce_mois": int,
      "contrats_par_famille": [
        { "code": str, "label": str, "total": int, "montant_annuel_ht": float }
      ],
      "commandes_par_statut": {
        "total": int,
        "nouvelles": int,
        "a_planifier": int,
        "planifiees": int,
        "facturees": int
      }
    }
    """
    aujourd_hui = date.today()
    mois_courant = aujourd_hui.month
    annee_courante = aujourd_hui.year

    # ── KPI globaux : contrats EN_COURS ─────────────────────
    total_contrats = (
        db.query(func.count(Contrat.id))
        .filter(Contrat.statut == "EN_COURS")
        .scalar()
        or 0
    )

    ca_annuel_ht = (
        db.query(func.coalesce(func.sum(Contrat.montant_annuel_ht), 0))
        .filter(Contrat.statut == "EN_COURS")
        .scalar()
        or 0
    )

    # ── À renouveler ce mois ─────────────────────────────────
    debut_mois = date(annee_courante, mois_courant, 1)
    if mois_courant == 12:
        fin_mois = date(annee_courante + 1, 1, 1)
    else:
        fin_mois = date(annee_courante, mois_courant + 1, 1)

    a_renouveler = (
        db.query(func.count(Contrat.id))
        .filter(
            Contrat.statut.in_(["EN_COURS", "A_RENOUVELER"]),
            Contrat.date_fin >= debut_mois,
            Contrat.date_fin < fin_mois,
        )
        .scalar()
        or 0
    )

    # ── Contrats par famille (EN_COURS uniquement) ──────────
    familles_rows = (
        db.query(
            Contrat.famille_contrat,
            func.count(Contrat.id),
            func.coalesce(func.sum(Contrat.montant_annuel_ht), 0),
        )
        .filter(Contrat.statut == "EN_COURS")
        .group_by(Contrat.famille_contrat)
        .order_by(func.count(Contrat.id).desc())
        .all()
    )

    contrats_par_famille = [
        {
            "code": code or "NON_CLASSE",
            "label": _label_famille(code),
            "total": int(total),
            "montant_annuel_ht": float(montant or 0),
        }
        for code, total, montant in familles_rows
    ]

    # ── Commandes par statut ────────────────────────────────
    commandes_rows = dict(
        db.query(Commande.statut, func.count(Commande.id))
        .group_by(Commande.statut)
        .all()
    )

    commandes_par_statut = {
        "total": sum(int(v) for v in commandes_rows.values()),
        "nouvelles": int(commandes_rows.get("nouvelle", 0)),
        "a_planifier": int(commandes_rows.get("a_planifier", 0)),
        "planifiees": int(commandes_rows.get("planifiee", 0)),
        "facturees": int(commandes_rows.get("facturee", 0)),
    }

    return {
        "total_contrats": int(total_contrats),
        "ca_annuel_ht": float(ca_annuel_ht),
        "a_renouveler_ce_mois": int(a_renouveler),
        "contrats_par_famille": contrats_par_famille,
        "commandes_par_statut": commandes_par_statut,
    }
