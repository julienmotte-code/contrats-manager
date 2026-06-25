"""
Service CA & marge par type de prestation.

Greffe sur le socle CA existant (cf. ca_service.py / modele KarliaCaFactures). La table
KarliaCaFactures n'agrege qu'au niveau FACTURE ; pour ventiler le CA et calculer la
marge par categorie d'article ("type de prestation"), il faut le niveau LIGNE.

Or les lignes ne figurent PAS dans le listing /documents (en-tetes seulement) : elles
ne sont disponibles que dans le DETAIL documents/{id} (cle products_list). On fait donc
un fetch N+1 (un detail par facture), avec le meme delai inter-appel que ca_service, et
on persiste un snapshot complet dans karlia_ca_lignes (DELETE + bulk insert).

Dimension "type de prestation" = product_category (id_product_category + libelle),
resolue via id_product -> article (une seule passe /products, filtrage local).

Cout par ligne :
  - total_cost de la ligne si present (>0)            -> source 'ligne'   (a privilegier)
  - sinon (cost_without_tax | weighted_average_cost) de l'article * quantite -> 'article'
  - sinon cout indisponible (prestations internes SGI sans cout d'achat)    -> 'absent'

On ne fetch le detail que des factures NON annulees (respect du quota : les annulees
sont de toute facon exclues du CA, cf. ca_service). Les regles de listing (id_type==4
re-filtre Python, numero_int en valeur absolue) sont reutilisees depuis ca_service.

Quota Karlia : delai DELAI_ENTRE_DETAILS entre deux GET. Cle API + URL lues via la
meme config/base que ca_service (jamais le .env en dur).
"""
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.models import KarliaCaLignes, Parametre
from app.services.ca_service import (
    KARLIA_TYPE_FACTURE,
    PAGE_SIZE,
    _cle_karlia,
    _numero_int,
    _parse_date,
    _to_decimal,
)

DELAI_ENTRE_PAGES = 0.8
DELAI_ENTRE_DETAILS = 0.8
PRODUCTS_PAGE_SIZE = 1000
DEFAUT_INTERVALLE_HEURES = 24
LIGNE_NON_CATEGORISEE = "(non catégorisé)"

# Axe d'agregation de l'ecran : FAMILLES comptables (chart_of_account_code), alignees
# sur l'Excel historique — et non product_category (33 categories, trop fin).
FAMILLE_NON_RATTACHEE = "(non rattaché)"

# Karlia marque les lignes sans compte par le libelle/code "?" : on les traite comme
# non rattachees (au meme titre que NULL/vide).
CODES_NON_RATTACHES = {None, "", "?"}

# Override des codes qui portent PLUSIEURS libelles dans la donnee Karlia : on impose un
# libelle canonique. Tout autre code prend son libelle modal (le plus frequent).
CANONICAL_LABELS = {
    "70701900": "Ventes de marchandises",
    "70601000": "Prestations de services",
}


def _base_url() -> str:
    return settings.KARLIA_API_URL.rstrip("/")


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


# ─────────────────────────────────────────────────────────────────────────────
# Index articles (categorie + cout) — une seule passe /products
# ─────────────────────────────────────────────────────────────────────────────
def _build_index_articles(client: httpx.Client, headers: dict) -> dict:
    """id_product (str) -> {categorie_id, categorie_nom, cost_without_tax,
    weighted_average_cost}.

    articles_cache ne porte pas le cout d'achat ; on interroge donc /products
    directement (filtrage local, AUCUN appel par id). Le catalogue tient en une page
    (limit 1000), on boucle quand meme par securite si volumineux."""
    index = {}
    offset = 0
    while True:
        r = client.get(
            f"{_base_url()}/products",
            params={"limit": PRODUCTS_PAGE_SIZE, "offset": offset},
            headers=headers,
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        for pr in data:
            pid = str(pr.get("id"))
            index[pid] = {
                "categorie_id": pr.get("id_product_category"),
                "categorie_nom": pr.get("product_category"),
                "cost_without_tax": _to_decimal(pr.get("cost_without_tax")),
                "weighted_average_cost": _to_decimal(pr.get("weighted_average_cost")),
            }
        if len(data) < PRODUCTS_PAGE_SIZE:
            break
        offset += PRODUCTS_PAGE_SIZE
        time.sleep(DELAI_ENTRE_PAGES)
    return index


# ─────────────────────────────────────────────────────────────────────────────
# Listing des en-tetes factures (memes regles que ca_service.rafraichir_karlia)
# ─────────────────────────────────────────────────────────────────────────────
def _lister_entetes(client: httpx.Client, headers: dict) -> list:
    offset, bruts = 0, []
    while True:
        r = client.get(
            f"{_base_url()}/documents",
            params={"type": KARLIA_TYPE_FACTURE, "limit": PAGE_SIZE, "offset": offset},
            headers=headers,
        )
        if r.status_code == 429:
            raise RuntimeError("Quota API Karlia depasse (429) pendant le listing des factures")
        r.raise_for_status()
        data = r.json().get("data", [])
        bruts.extend(data)
        if len(data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(DELAI_ENTRE_PAGES)
    # re-filtre id_type==4 en Python (le serveur laisse passer du type 6 / avoirs)
    return [d for d in bruts if str(d.get("id_type")) == str(KARLIA_TYPE_FACTURE)]


def _montant_ligne(ln: dict) -> Decimal:
    v = ln.get("total_without_tax")
    if v not in (None, ""):
        return _to_decimal(v)
    return _to_decimal(ln.get("price_without_tax")) * _to_decimal(ln.get("quantity") or 0)


def _chart_of_account(ln: dict):
    coa = ln.get("chart_of_account")
    if isinstance(coa, dict):
        return coa.get("code"), (coa.get("title") or coa.get("label"))
    if isinstance(coa, str) and coa:
        return None, coa
    return None, None


def _resoudre_cout(ln: dict, qte: Decimal, meta: dict):
    """Retourne (cout: Decimal, source: str, disponible: bool)."""
    cout_ligne = _to_decimal(ln.get("total_cost"))
    if cout_ligne > 0:
        return cout_ligne, "ligne", True
    cout_unit = Decimal("0")
    if meta:
        cout_unit = meta.get("cost_without_tax") or Decimal("0")
        if cout_unit <= 0:
            cout_unit = meta.get("weighted_average_cost") or Decimal("0")
    cout_article = cout_unit * qte
    if cout_article > 0:
        return cout_article, "article", True
    return Decimal("0"), "absent", False


# ─────────────────────────────────────────────────────────────────────────────
# Rafraichissement : snapshot complet des lignes (calque sur rafraichir_karlia)
# ─────────────────────────────────────────────────────────────────────────────
def rafraichir_lignes(db: Session, progress=None) -> int:
    """Remplace integralement le miroir lignes Karlia. Retourne le nb de lignes inserees.

    On ACCUMULE tous les objets en memoire pendant la boucle detail (~72 s) et on ne
    fait DELETE + bulk_save_objects + commit QU'A LA FIN : la fenetre "table vide" est
    reduite a la seule insertion, pas a toute la duree du fetch.

    `progress(traitees, total)` est appele a chaque facture si fourni (suivi de la tache
    de fond, cf. demarrer_refresh_async)."""
    api_key = _cle_karlia(db)
    if not api_key:
        raise RuntimeError("Cle API Karlia absente en base (parametres.karlia_api_key)")

    base = _base_url()
    headers = _headers(api_key)
    now = datetime.utcnow()
    objs = []

    with httpx.Client(timeout=40) as client:
        index = _build_index_articles(client, headers)
        time.sleep(DELAI_ENTRE_DETAILS)

        entetes = _lister_entetes(client, headers)
        # Quota : on ne descend dans le detail que des factures retenues (non annulees).
        entetes = [d for d in entetes if str(d.get("canceled")) != "1"]
        total = len(entetes)
        if progress:
            progress(0, total)

        for i, d in enumerate(entetes, 1):
            doc_id = d.get("id")
            r = client.get(f"{base}/documents/{doc_id}", headers=headers)
            time.sleep(DELAI_ENTRE_DETAILS)
            if r.status_code == 429:
                raise RuntimeError("Quota API Karlia depasse (429) pendant le fetch detail")
            if r.status_code != 200:
                print(f"[ca_marges] detail doc {doc_id} -> HTTP {r.status_code} (ignore)")
                continue

            payload = r.json()
            node = payload.get("data") if isinstance(payload.get("data"), dict) else payload
            lignes = (node or {}).get("products_list") or []

            dt = _parse_date(d.get("date"))
            exercice = dt.year if dt else None
            numero = str(d.get("number")) if d.get("number") is not None else None
            numero_int = _numero_int(d.get("number"))

            for ln in lignes:
                qte = _to_decimal(ln.get("quantity") or 0)
                montant = _montant_ligne(ln)

                pid = ln.get("id_product")
                pid_str = str(pid) if pid not in (None, "", 0, "0") else None
                meta = index.get(pid_str) if pid_str else None

                cout, cout_source, dispo = _resoudre_cout(ln, qte, meta)

                if meta and meta.get("categorie_id") is not None:
                    categorie_id = meta.get("categorie_id")
                    categorie_nom = meta.get("categorie_nom") or LIGNE_NON_CATEGORISEE
                else:
                    categorie_id = None
                    categorie_nom = LIGNE_NON_CATEGORISEE

                coa_code, coa_label = _chart_of_account(ln)

                objs.append(KarliaCaLignes(
                    source="karlia",
                    karlia_document_id=str(doc_id),
                    numero=numero,
                    numero_int=numero_int,
                    date_facture=dt,
                    exercice=exercice,
                    canceled=False,
                    id_product=pid_str,
                    categorie_id=categorie_id,
                    categorie_nom=categorie_nom,
                    chart_of_account_code=coa_code,
                    chart_of_account_label=coa_label,
                    title=ln.get("title"),
                    quantity=qte,
                    montant_ht=montant,
                    cout=cout,
                    cout_source=cout_source,
                    cout_disponible=dispo,
                    refreshed_at=now,
                ))

            if progress:
                progress(i, total)
            if i % 10 == 0 or i == total:
                print(f"[ca_marges] {i}/{total} factures traitees — {len(objs)} lignes")

    db.query(KarliaCaLignes).delete(synchronize_session=False)
    db.bulk_save_objects(objs)
    db.commit()
    return len(objs)


# ─────────────────────────────────────────────────────────────────────────────
# Rafraichissement paresseux (calque sur ca_service.rafraichir_si_perime)
# ─────────────────────────────────────────────────────────────────────────────
def _intervalle_refresh_heures(db: Session) -> float:
    p = db.query(Parametre).filter(Parametre.cle == "ca_lignes_refresh_interval_heures").first()
    if p and p.valeur:
        try:
            return max(0.0, float(str(p.valeur).replace(",", ".")))
        except ValueError:
            pass
    return float(DEFAUT_INTERVALLE_HEURES)


def rafraichir_si_perime(db: Session) -> dict:
    """Rafraichit le miroir lignes seulement s'il est plus vieux que l'intervalle.
    Ne leve jamais : repli silencieux sur le dernier snapshot en cas d'echec Karlia."""
    dernier = db.query(func.max(KarliaCaLignes.refreshed_at)).scalar()
    intervalle = _intervalle_refresh_heures(db)
    perime = (dernier is None) or (datetime.utcnow() - dernier >= timedelta(hours=intervalle))

    if not perime:
        return {"refreshed": False, "stale": False,
                "refreshed_at": dernier.isoformat() if dernier else None, "raison": "cache_frais"}

    try:
        n = rafraichir_lignes(db)
        nouveau = db.query(func.max(KarliaCaLignes.refreshed_at)).scalar()
        return {"refreshed": True, "stale": False, "nb_lignes": n,
                "refreshed_at": nouveau.isoformat() if nouveau else None, "raison": "rafraichi"}
    except Exception as e:
        return {"refreshed": False, "stale": dernier is not None,
                "refreshed_at": dernier.isoformat() if dernier else None,
                "raison": f"echec_karlia:{type(e).__name__}"}


def etat_donnees(db: Session) -> dict:
    """Etat du miroir SANS appel Karlia : {"vide": bool, "perime": bool}.

    Sert au chemin GET pour decider s'il faut declencher un refresh de fond, sans jamais
    bloquer sur le reseau (cf. timeout 524 Cloudflare sur le N+1 synchrone)."""
    dernier = db.query(func.max(KarliaCaLignes.refreshed_at)).scalar()
    if dernier is None:
        return {"vide": True, "perime": True}
    intervalle = _intervalle_refresh_heures(db)
    perime = (datetime.utcnow() - dernier) >= timedelta(hours=intervalle)
    return {"vide": False, "perime": perime}


# ─────────────────────────────────────────────────────────────────────────────
# Refresh ASYNCHRONE (tache de fond) + state mono-process
#
# Le fetch detail N+1 dure ~72 s : derriere Cloudflare (timeout 524 a 120 s) un refresh
# synchrone est intenable. On lance donc un thread daemon et on expose un state en
# memoire interrogeable par polling. MONO-PROCESS uniquement (uvicorn 1 worker, cf.
# synchro_state dans main.py) : a redessiner en state DB pour un deploiement multi-worker.
# ─────────────────────────────────────────────────────────────────────────────
_refresh_state = {
    "etat": "idle",        # idle | en_cours | termine | erreur
    "traitees": 0,
    "total": 0,
    "message": "",
    "demarre_at": None,
    "fin_at": None,
}
_refresh_lock = threading.Lock()


def get_refresh_state() -> dict:
    """Copie thread-safe du state courant (serialisable JSON)."""
    with _refresh_lock:
        return dict(_refresh_state)


def _run_refresh():
    """Corps du thread : session DEDIEE (jamais celle d'une requete), maj du state."""
    db = SessionLocal()
    try:
        def _progress(traitees, total):
            with _refresh_lock:
                _refresh_state["traitees"] = traitees
                _refresh_state["total"] = total

        n = rafraichir_lignes(db, progress=_progress)
        with _refresh_lock:
            _refresh_state["etat"] = "termine"
            _refresh_state["message"] = f"{n} lignes"
            _refresh_state["fin_at"] = datetime.utcnow().isoformat()
    except Exception as e:
        print(f"[ca_marges] refresh async ERREUR: {type(e).__name__}: {e}")
        with _refresh_lock:
            _refresh_state["etat"] = "erreur"
            _refresh_state["message"] = str(e)[:300]
            _refresh_state["fin_at"] = datetime.utcnow().isoformat()
    finally:
        db.close()


def demarrer_refresh_async() -> dict:
    """Lance le refresh de fond s'il n'est pas deja en cours (idempotent). Retourne le
    state courant immediatement (ne bloque jamais)."""
    with _refresh_lock:
        if _refresh_state["etat"] == "en_cours":
            return dict(_refresh_state)
        _refresh_state["etat"] = "en_cours"
        _refresh_state["traitees"] = 0
        _refresh_state["total"] = 0
        _refresh_state["message"] = ""
        _refresh_state["demarre_at"] = datetime.utcnow().isoformat()
        _refresh_state["fin_at"] = None
        etat_initial = dict(_refresh_state)

    threading.Thread(target=_run_refresh, daemon=True).start()
    return etat_initial


# ─────────────────────────────────────────────────────────────────────────────
# Agregation CA & marge par categorie
# ─────────────────────────────────────────────────────────────────────────────
def _f(x) -> float:
    return float(round(_to_decimal(x), 2))


def _pct(num, den, ndigits=1) -> float:
    return float(round(100 * num / den, ndigits)) if den else 0.0


def _famille_label(code, label_counts: dict) -> str:
    """Libelle canonique d'une famille : override CANONICAL_LABELS, sinon libelle modal
    (le plus frequent) parmi les lignes du code, sinon le code lui-meme."""
    if code in CANONICAL_LABELS:
        return CANONICAL_LABELS[code]
    if label_counts:
        # modal : libelle le plus frequent (tie-break alphabetique stable)
        return max(sorted(label_counts), key=lambda lab: label_counts[lab])
    return str(code)


def agreger_marges(db: Session, exercice: int = None) -> dict:
    """Agrege le miroir lignes (hors annulees) en CA / cout / marge par FAMILLE comptable
    (chart_of_account_code), axe aligne sur l'Excel historique.

    Les familles presentes sont PILOTEES PAR LA DONNEE (variables selon l'exercice) : on
    n'enumere jamais une liste figee. Familles internes (cout indisponible) : marge = ca_ht,
    taux = 100%, cout_disponible_pct = 0. Lignes a code NULL/vide/"?" -> "(non rattaché)"."""
    q = db.query(KarliaCaLignes).filter(KarliaCaLignes.canceled.is_(False))
    if exercice is not None:
        q = q.filter(KarliaCaLignes.exercice == exercice)
    lignes = q.all()

    familles = {}
    total_ca = Decimal("0")
    total_cout = Decimal("0")
    ca_non_rattache = Decimal("0")
    nb_lignes = 0
    nb_lignes_sans_cout = 0

    for l in lignes:
        ca = _to_decimal(l.montant_ht)
        cout = _to_decimal(l.cout) if l.cout is not None else Decimal("0")
        nb_lignes += 1
        total_ca += ca
        total_cout += cout
        if not l.cout_disponible:
            nb_lignes_sans_cout += 1

        code = l.chart_of_account_code
        if code in CODES_NON_RATTACHES:
            code = None
            ca_non_rattache += ca

        agg = familles.setdefault(code, {
            "code": code,
            "ca_ht": Decimal("0"), "cout": Decimal("0"),
            "nb_lignes": 0, "nb_lignes_cout_dispo": 0,
            "label_counts": {},
        })
        agg["ca_ht"] += ca
        agg["cout"] += cout
        agg["nb_lignes"] += 1
        if l.cout_disponible:
            agg["nb_lignes_cout_dispo"] += 1
        if code is not None and l.chart_of_account_label:
            lab = l.chart_of_account_label
            agg["label_counts"][lab] = agg["label_counts"].get(lab, 0) + 1

    liste_familles = []
    for agg in familles.values():
        ca = agg["ca_ht"]
        cout = agg["cout"]
        marge = ca - cout
        code = agg["code"]
        # Le bucket "non rattache" (code NULL/vide/"?") ne porte que des lignes a 0 € :
        # son montant est deja surface via ca_non_categorise_ht, inutile de l'afficher.
        if code is None and ca == 0:
            continue
        famille = FAMILLE_NON_RATTACHEE if code is None else _famille_label(code, agg["label_counts"])
        liste_familles.append({
            "code": code,
            "famille": famille,
            "ca_ht": _f(ca),
            "cout": _f(cout),
            "marge": _f(marge),
            "taux_marge": _pct(marge, ca),
            "part_ca_pct": _pct(ca, total_ca),
            "cout_disponible_pct": _pct(agg["nb_lignes_cout_dispo"], agg["nb_lignes"]),
        })
    liste_familles.sort(key=lambda f: f["ca_ht"], reverse=True)

    total_marge = total_ca - total_cout
    last = db.query(func.max(KarliaCaLignes.refreshed_at)).scalar()
    return {
        "exercice": exercice,
        "total_ca_ht": _f(total_ca),
        "total_cout": _f(total_cout),
        "total_marge": _f(total_marge),
        "taux_marge_global": _pct(total_marge, total_ca),
        "ca_non_categorise_ht": _f(ca_non_rattache),
        "lignes_sans_cout_pct": _pct(nb_lignes_sans_cout, nb_lignes),
        "nb_lignes": nb_lignes,
        "familles": liste_familles,
        "karlia_last_refresh": last.isoformat() if last else None,
    }
