"""
Service de calcul du chiffre d'affaires pluriannuel.

Sources complementaires (frontiere = n°8900, aucun recouvrement) :
- factures_historiques : factures emises (export Factura), n° 1..8900.
- karlia_ca_factures   : miroir des ventes Karlia (n° 8901+), rafraichi a la demande.

Regle CA Karlia (verifiee sur donnees reelles) :
- id_type == 4 (re-filtre Python : le serveur laisse passer du type 6 / avoirs)
- canceled != '1'  (le flag 'canceled' du listing distingue Annule vs En attente,
  contrairement a id_status qui fusionne les deux sous '1')
- montant = total_without_tax (string -> Decimal), exercice = annee de 'date' (ISO)

Normalisation du numero a l'ingestion : certains 'number' Karlia portent un prefixe
'-' (erreur de parametrage initial, transitoire et NON semantique). On stocke le
'number' brut signe dans la colonne 'numero' (tracabilite) et on derive 'numero_int'
en VALEUR ABSOLUE (on ignore le signe parasite) pour la comparaison a la borne
historique.
"""
import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import httpx
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.models import FactureHistorique, KarliaCaFactures, Parametre

KARLIA_TYPE_FACTURE = 4
PAGE_SIZE = 100
DELAI_ENTRE_PAGES = 0.8
BORNE_HISTORIQUE = 8900  # dernier numero couvert par l'historique


def _cle_karlia(db: Session) -> str:
    p = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
    return (p.valeur if p and p.valeur else "").strip()


def _to_decimal(v) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _numero_int(number):
    if number is None:
        return None
    m = re.search(r"\d+", str(number))   # \d+ : on ignore le signe parasite
    return int(m.group()) if m else None


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def rafraichir_karlia(db: Session) -> dict:
    """Remplace integralement le miroir des ventes Karlia (snapshot complet)."""
    api_key = _cle_karlia(db)
    if not api_key:
        raise RuntimeError("Cle API Karlia absente en base (parametres.karlia_api_key)")

    base = settings.KARLIA_API_URL.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}

    offset, bruts = 0, []
    with httpx.Client(timeout=40) as client:
        while True:
            r = client.get(
                f"{base}/documents",
                params={"type": KARLIA_TYPE_FACTURE, "limit": PAGE_SIZE, "offset": offset},
                headers=headers,
            )
            if r.status_code == 429:
                raise RuntimeError("Quota API Karlia depasse (429) pendant le rafraichissement")
            r.raise_for_status()
            data = r.json().get("data", [])
            bruts.extend(data)
            if len(data) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
            time.sleep(DELAI_ENTRE_PAGES)

    factures = [d for d in bruts if str(d.get("id_type")) == str(KARLIA_TYPE_FACTURE)]

    now = datetime.utcnow()
    objs, nb_annulees = [], 0
    for d in factures:
        dt = _parse_date(d.get("date"))
        if dt is None:
            continue
        canceled = str(d.get("canceled")) == "1"
        if canceled:
            nb_annulees += 1
        objs.append(KarliaCaFactures(
            karlia_document_id=str(d.get("id")),
            numero=(str(d.get("number")) if d.get("number") is not None else None),
            numero_int=_numero_int(d.get("number")),
            date_facture=dt,
            exercice=dt.year,
            montant_ht=_to_decimal(d.get("total_without_tax")),
            montant_ttc=_to_decimal(d.get("total_with_tax")),
            canceled=canceled,
            client_nom=d.get("customer_supplier_title"),
            id_opportunity=(str(d.get("id_opportunity")) if d.get("id_opportunity") is not None else None),
            refreshed_at=now,
        ))

    db.query(KarliaCaFactures).delete(synchronize_session=False)
    db.bulk_save_objects(objs)
    db.commit()

    return {
        "refreshed_at": now.isoformat(),
        "nb_factures_total": len(objs),
        "nb_retenues": sum(1 for o in objs if not o.canceled),
        "nb_annulees": nb_annulees,
    }


def _shift_annee(d: date, annee: int) -> date:
    try:
        return d.replace(year=annee)
    except ValueError:  # 29 fevrier -> annee non bissextile
        return d.replace(year=annee, day=28)


def _ca_periode(db: Session, debut: date, fin: date) -> dict:
    h = db.query(
        func.coalesce(func.sum(FactureHistorique.montant_ht), 0),
        func.count(FactureHistorique.id),
    ).filter(
        FactureHistorique.date_facture >= debut,
        FactureHistorique.date_facture <= fin,
    ).one()

    k = db.query(
        func.coalesce(func.sum(KarliaCaFactures.montant_ht), 0),
        func.count(KarliaCaFactures.id),
    ).filter(
        KarliaCaFactures.canceled.is_(False),
        or_(
            KarliaCaFactures.numero_int.is_(None),
            KarliaCaFactures.numero_int > BORNE_HISTORIQUE,
        ),
        KarliaCaFactures.date_facture >= debut,
        KarliaCaFactures.date_facture <= fin,
    ).one()

    ht_h, ht_k = Decimal(h[0] or 0), Decimal(k[0] or 0)
    return {
        "ca_historique": float(round(ht_h, 2)),
        "ca_karlia": float(round(ht_k, 2)),
        "ca_total": float(round(ht_h + ht_k, 2)),
        "nb_factures_historique": int(h[1]),
        "nb_factures_karlia": int(k[1]),
    }


def calculer_comparatif(db: Session, date_debut: date, date_fin: date, n_exercices: int = 5) -> dict:
    annee_ref = date_fin.year
    lignes = []
    for k in range(0, n_exercices + 1):
        annee = annee_ref - k
        debut, fin = _shift_annee(date_debut, annee), _shift_annee(date_fin, annee)
        ligne = _ca_periode(db, debut, fin)
        ligne.update({"exercice": annee, "date_debut": debut.isoformat(), "date_fin": fin.isoformat()})
        lignes.append(ligne)
    last = db.query(func.max(KarliaCaFactures.refreshed_at)).scalar()
    return {
        "reference": lignes[0],
        "comparatif": lignes,  # [0] = exercice de reference, puis anterieurs
        "karlia_last_refresh": last.isoformat() if last else None,
    }


DEFAUT_INTERVALLE_HEURES = 2


def _intervalle_refresh_heures(db: Session) -> float:
    p = db.query(Parametre).filter(Parametre.cle == "ca_refresh_interval_heures").first()
    if p and p.valeur:
        try:
            return max(0.0, float(str(p.valeur).replace(",", ".")))
        except ValueError:
            pass
    return float(DEFAUT_INTERVALLE_HEURES)


def rafraichir_si_perime(db: Session) -> dict:
    """Rafraichit le miroir Karlia uniquement s'il est plus vieux que l'intervalle configure.
    Ne leve jamais : en cas d'echec Karlia, on conserve le dernier miroir connu (repli silencieux).
    Retourne l'etat : {refreshed: bool, stale: bool, refreshed_at: iso|None, raison: str}.
    """
    dernier = db.query(func.max(KarliaCaFactures.refreshed_at)).scalar()
    intervalle = _intervalle_refresh_heures(db)
    perime = (dernier is None) or (datetime.utcnow() - dernier >= timedelta(hours=intervalle))

    if not perime:
        return {"refreshed": False, "stale": False,
                "refreshed_at": dernier.isoformat() if dernier else None, "raison": "cache_frais"}

    try:
        rafraichir_karlia(db)
        nouveau = db.query(func.max(KarliaCaFactures.refreshed_at)).scalar()
        return {"refreshed": True, "stale": False,
                "refreshed_at": nouveau.isoformat() if nouveau else None, "raison": "rafraichi"}
    except Exception as e:
        # Repli silencieux : on garde le dernier miroir. stale=True seulement s'il existait deja des donnees.
        return {"refreshed": False, "stale": dernier is not None,
                "refreshed_at": dernier.isoformat() if dernier else None,
                "raison": f"echec_karlia:{type(e).__name__}"}


def ca_annee_en_cours(db: Session) -> dict:
    """CA facture reel du 1er janvier de l'annee courante a aujourd'hui (= reference du comparatif)."""
    today = date.today()
    res = calculer_comparatif(db, date(today.year, 1, 1), today, n_exercices=0)
    ref = res["reference"]
    return {
        "ca_total": ref["ca_total"],
        "ca_historique": ref["ca_historique"],
        "ca_karlia": ref["ca_karlia"],
        "exercice": today.year,
        "date_debut": res["comparatif"][0]["date_debut"],
        "date_fin": res["comparatif"][0]["date_fin"],
    }
