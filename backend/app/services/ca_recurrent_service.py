"""
Service CA recurrent par famille de contrat.

Source = plan_facturation.montant_ht_prevu (montant PREVU des echeances), groupe par
Contrat.famille_contrat. C'est le carnet recurrent CONTRACTUEL : distinct et complementaire
de l'ecran "CA par prestation" (ca_marges_service), qui agrege le CA Karlia REELLEMENT
facture par famille comptable.

Perimetre : toutes les echeances de l'annee (annee_facturation == annee), tous statuts
confondus. Lecture DB pure (aucune ecriture, aucun appel Karlia) => instantane.

Les familles affichees sont PILOTEES PAR LA DONNEE (pas d'enumeration en dur) : on ne
montre que celles presentes pour l'annee. contrat_id NULL ou famille absente -> "(sans famille)".

memo_karlia_vente_log : sous-detail d'information ("dont deja facture via Karlia" sur le
compte 70702000 = vente logiciels). C'est un PERIMETRE DIFFERENT (CA Karlia reel, fenetre
partielle) — il ne s'additionne JAMAIS au total recurrent.
"""
from collections import defaultdict

from sqlalchemy.orm import Session

from app.models.models import Contrat, KarliaCaLignes, PlanFacturation

FAMILLE_SANS = "(sans famille)"
KARLIA_COMPTE_VENTE_LOGICIELS = "70702000"


def _f(x) -> float:
    return float(round(float(x or 0), 2))


def _pct(num: float, den: float, ndigits: int = 1) -> float:
    return round(100 * num / den, ndigits) if den else 0.0


def _memo_karlia_vente_log(db: Session) -> float:
    """Somme montant_ht des lignes Karlia du compte vente logiciels (hors annulees).
    Memo informatif uniquement — perimetre distinct, non additionne au recurrent."""
    total = 0.0
    rows = (
        db.query(KarliaCaLignes.montant_ht)
        .filter(
            KarliaCaLignes.canceled.is_(False),
            KarliaCaLignes.chart_of_account_code == KARLIA_COMPTE_VENTE_LOGICIELS,
        )
        .all()
    )
    for (montant,) in rows:
        total += float(montant or 0)
    return _f(total)


def agreger_recurrent(db: Session, annee: int) -> dict:
    """Agrege le recurrent (plan_facturation.montant_ht_prevu) de l'annee par famille de
    contrat. Retourne total, nb echeances, familles triees par CA desc, et le memo Karlia."""
    # map contrat_id -> famille en UNE requete (pas de N+1)
    fam_de = {
        cid: (fam or FAMILLE_SANS)
        for cid, fam in db.query(Contrat.id, Contrat.famille_contrat).all()
    }

    ca_fam = defaultdict(float)
    nb_fam = defaultdict(int)
    total_ca = 0.0
    nb_echeances = 0

    echeances = (
        db.query(PlanFacturation.contrat_id, PlanFacturation.montant_ht_prevu)
        .filter(PlanFacturation.annee_facturation == annee)
        .all()
    )
    for contrat_id, montant_prevu in echeances:
        m = float(montant_prevu or 0)
        famille = fam_de.get(contrat_id, FAMILLE_SANS) if contrat_id is not None else FAMILLE_SANS
        ca_fam[famille] += m
        nb_fam[famille] += 1
        total_ca += m
        nb_echeances += 1

    familles = [
        {
            "famille": fam,
            "ca_ht": _f(ca),
            "nb_echeances": nb_fam[fam],
            "part_pct": _pct(ca, total_ca),
        }
        for fam, ca in ca_fam.items()
    ]
    familles.sort(key=lambda x: x["ca_ht"], reverse=True)

    return {
        "annee": annee,
        "total_ca_ht": _f(total_ca),
        "nb_echeances": nb_echeances,
        "familles": familles,
        "memo_karlia_vente_log": _memo_karlia_vente_log(db),
    }
