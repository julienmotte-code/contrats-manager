"""
Recapitulatif de marge FUSIONNE : Excel historique + prolongement Karlia.

Le recap d'une annee = marge brute par famille (chart_of_account) x 12 mois, construite
en deux sources complementaires, sans recouvrement :

  - EXCEL  (ca_recap_excel)   : factures <= 9002, deja importees (cf. ca_recap_service).
  - KARLIA (karlia_ca_lignes) : factures numero_int > 9002 STRICT, marge ligne = PV - PA
    (montant_ht - cout), ventilee au mois via date_facture, regroupee par
    chart_of_account_code.

La borne 9002 est la garde anti-doublon : les lignes Karlia 8903-9002 figurent DEJA dans
l'Excel 2026, on ne reprend donc que le STRICTEMENT superieur. A partir de 2027 il n'y a
plus d'Excel : le recap devient Karlia seul (>9002 naturellement).

Schema de sortie (retro-compatible avec ca_recap_service.get_recap) :
  { annee, mois_labels[12], familles:[{code, famille, mois:[12], total,
      total_n1, variation_pct, statut_var}], totaux_mois[12], total_annee }
Les champs total_n1 / variation_pct / statut_var sont AJOUTES (variation N/N-1 par code) ;
le front qui les ignore continue de fonctionner.

Lecture DB pure : aucune ecriture, aucun appel Karlia externe. Robuste si annee sans
Excel (base vide) ou sans Karlia >9002 (rend l'Excel tel quel).
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.models import KarliaCaLignes
from app.services import ca_recap_service
from app.services.ca_marges_service import (
    CANONICAL_LABELS,        # reutilise (import explicite documente)  # noqa: F401
    CODES_NON_RATTACHES,
    _famille_label,
)

# Derniere facture couverte par l'Excel 2026 : on ne prolonge qu'au-dela (anti-doublon).
BORNE_RECAP_KARLIA = 9002


def _d(x):
    return None if x is None else Decimal(str(x))


def _f2(x):
    return None if x is None else float(round(x, 2))


def _agreger_karlia(db: Session, annee: int) -> dict:
    """code -> {"label_counts": {...}, "mois": [Decimal]*12} pour les lignes Karlia
    de l'annee, factures > BORNE_RECAP_KARLIA, hors bruit (TEST / non rattache)."""
    lignes = (
        db.query(KarliaCaLignes)
        .filter(
            KarliaCaLignes.canceled.is_(False),
            KarliaCaLignes.exercice == annee,
            KarliaCaLignes.numero_int > BORNE_RECAP_KARLIA,
        )
        .all()
    )
    agg = {}
    for L in lignes:
        code = L.chart_of_account_code
        if code in CODES_NON_RATTACHES:                 # NULL / '' / '?'
            continue
        if "TEST" in (L.title or "").upper():           # articles de test -> bruit
            continue
        d = L.date_facture
        if d is None or not (1 <= d.month <= 12):
            continue
        marge = (_d(L.montant_ht) or Decimal("0")) - (_d(L.cout) or Decimal("0"))
        e = agg.setdefault(code, {"label_counts": {}, "mois": [Decimal("0")] * 12})
        e["mois"][d.month - 1] += marge                 # marge negative conservee
        lab = L.chart_of_account_label
        if lab:
            e["label_counts"][lab] = e["label_counts"].get(lab, 0) + 1
    return agg


def _recap_fusionne_core(db: Session, annee: int) -> dict:
    """Coeur de la fusion Excel + Karlia, SANS les champs de variation N/N-1.
    Retourne { annee, mois_labels, familles:[{code, famille, mois, total}],
    totaux_mois, total_annee }."""
    base = ca_recap_service.get_recap(db, annee)

    # Familles Excel -> entrees mutables (mois en Decimal|None), ordre conserve.
    familles = []
    code_to_idx = {}
    for fam in base["familles"]:
        familles.append({
            "code": fam["code"],
            "famille": fam["famille"],
            "mois": [_d(v) for v in fam["mois"]],
        })
        if fam["code"] is not None and fam["code"] not in code_to_idx:
            code_to_idx[fam["code"]] = len(familles) - 1   # 1re occurrence du code

    # Prolongement Karlia (> 9002), fusionne par code.
    for code, e in _agreger_karlia(db, annee).items():
        if code in code_to_idx:
            entry = familles[code_to_idx[code]]
            for k in range(12):
                if e["mois"][k] != 0:
                    entry["mois"][k] = (entry["mois"][k] or Decimal("0")) + e["mois"][k]
        else:
            mois = [e["mois"][k] if e["mois"][k] != 0 else None for k in range(12)]
            familles.append({
                "code": code,
                "famille": _famille_label(code, e["label_counts"]),
                "mois": mois,
            })

    # Recalcul totaux par famille + totaux_mois + total_annee.
    totaux_mois = [Decimal("0")] * 12
    out = []
    for entry in familles:
        total = Decimal("0")
        mois_out = []
        for k in range(12):
            v = entry["mois"][k]
            if v is not None:
                total += v
                totaux_mois[k] += v
            mois_out.append(_f2(v))
        out.append({"code": entry["code"], "famille": entry["famille"],
                    "mois": mois_out, "total": float(round(total, 2))})

    return {
        "annee": annee,
        "mois_labels": base["mois_labels"],
        "familles": out,
        "totaux_mois": [float(round(x, 2)) for x in totaux_mois],
        "total_annee": float(round(sum(totaux_mois, Decimal("0")), 2)),
    }


def _totaux_par_code(db: Session, annee: int) -> dict:
    """{code: total} pour l'annee (recap fusionne), pour la comparaison N/N-1.
    Si un code porte plusieurs familles, les totaux sont additionnes."""
    totaux = {}
    for fam in _recap_fusionne_core(db, annee)["familles"]:
        code = fam["code"]
        if code is None:
            continue
        totaux[code] = round(totaux.get(code, 0.0) + (fam["total"] or 0.0), 2)
    return totaux


def get_recap_fusionne(db: Session, annee: int) -> dict:
    """Recap fusionne de l'annee + variation N/N-1 par famille (cle = code_compte).
    Champs ajoutes par famille : total_n1, variation_pct, statut_var."""
    recap = _recap_fusionne_core(db, annee)
    totaux_n1 = _totaux_par_code(db, annee - 1)

    for fam in recap["familles"]:
        code = fam["code"]
        total_n1 = totaux_n1.get(code) if code is not None else None
        if total_n1 is None:
            statut, variation = "nouveau", None
        elif total_n1 == 0:
            statut, variation = "n1_zero", None
        else:
            statut = "ok"
            variation = round((fam["total"] - total_n1) / total_n1 * 100, 1)
        fam["total_n1"] = total_n1
        fam["variation_pct"] = variation
        fam["statut_var"] = statut

    return recap
