"""
Diagnostic LECTURE SEULE — universalité du champ 'section' sur les lignes
de products_list Karlia. Échantillon de 10 commandes variées.

Charge la clé Karlia depuis la base. Rate-limit 1s entre GET. Aucune
écriture Karlia, aucune opportunité marquée.
"""
import asyncio
import json
from collections import Counter, defaultdict
from typing import Any, Dict, List

import httpx

from app.core.database import SessionLocal
from app.models.models import Parametre

BASE = "https://karlia.fr/app/api/v2"
DELAI_S = 1.0

SAMPLE = [
    # (karlia_document_id, reference_devis, client_nom) — échantillon SQL ci-dessus
    (677325, "BC26-0023", "MAIRIE DE GUEMPS"),
    (677637, "BC25-0050", "MAIRIE DE CAMPAGNE LÈS GUINES"),
    (677593, "BC26-0037", "MAIRIE DE BLEQUIN"),
    (676859, "BC26-0012", "MAIRIE DE COURCELLES LES LENS"),
    (681715, "BC26-0069", "MAIRIE DE MOUCHIN"),
    (677285, "BC26-0019", "MAIRIE DE ANIZY LE GRAND"),
    (678054, "BC26-0062", "MAIRIE DE FENAIN"),
    (449263, "BC25-0002", "MAIRIE DE TEST"),
    (677608, "BC25-0042", "CCAS DE LALLAING"),
    (677316, "BC26-0022", "MAIRIE DE CHARLY SUR MARNE"),
]


def load_key() -> str:
    db = SessionLocal()
    try:
        p = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
        if not p or not p.valeur:
            raise SystemExit("Clé karlia_api_key absente.")
        return p.valeur
    finally:
        db.close()


def looks_like_title(line: Dict[str, Any]) -> bool:
    """Heuristique œil : designation majuscules dominantes + id_product=0 + montant=0."""
    title = (line.get("title") or "").strip()
    if not title:
        return False
    id_prod = str(line.get("id_product") or "")
    total = str(line.get("total_without_tax") or "")
    price = str(line.get("price_without_tax") or "")
    try:
        is_zero = float(total or 0) == 0.0 and float(price or 0) == 0.0
    except ValueError:
        is_zero = False
    lettres = [c for c in title if c.isalpha()]
    if not lettres:
        majuscule_ratio = 0.0
    else:
        majuscule_ratio = sum(1 for c in lettres if c.isupper()) / len(lettres)
    # Heuristique conservatrice : à la fois id_product=0, montants 0, et au moins 60% majuscules
    return id_prod in ("0", "") and is_zero and majuscule_ratio >= 0.6


async def main():
    key = load_key()
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    counter_section: Counter = Counter()
    presence_section: Counter = Counter()    # how many lines actually have the key
    par_commande_section_1: List[tuple] = [] # (kdoc_id, ref, ligne_index, title, id_product, total)
    par_commande_total_lignes: Dict[int, int] = {}
    par_commande_section_1_n: Dict[int, int] = {}
    faux_negatifs_oeil: List[tuple] = []

    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30.0) as cl:
        for idx, (kdoc_id, ref, client) in enumerate(SAMPLE):
            print(f"\n=== ({idx+1}/{len(SAMPLE)}) GET /documents/{kdoc_id}  [{ref} — {client}] ===")
            r = await cl.get(f"/documents/{kdoc_id}")
            if r.status_code != 200:
                print(f"  HTTP {r.status_code} — SKIP")
                await asyncio.sleep(DELAI_S)
                continue
            data = r.json()
            plist = data.get("products_list") or []
            par_commande_total_lignes[kdoc_id] = len(plist)
            n_sec1 = 0
            for i, line in enumerate(plist):
                section = line.get("section", "<absent>") if "section" in line else "<absent>"
                counter_section[str(section)] += 1
                if "section" in line:
                    presence_section["present"] += 1
                else:
                    presence_section["absent"] += 1
                # collecte des section='1' pour échantillon visuel
                if str(section) == "1":
                    n_sec1 += 1
                    par_commande_section_1.append((
                        kdoc_id, ref, i,
                        (line.get("title") or "")[:80],
                        str(line.get("id_product") or ""),
                        str(line.get("total_without_tax") or "")
                    ))
                # Faux négatifs : œil-intitulé mais section != '1'
                if str(section) != "1" and looks_like_title(line):
                    faux_negatifs_oeil.append((
                        kdoc_id, ref, i, str(section),
                        (line.get("title") or "")[:80],
                        str(line.get("id_product") or ""),
                        str(line.get("total_without_tax") or "")
                    ))
            par_commande_section_1_n[kdoc_id] = n_sec1
            print(f"  {len(plist)} lignes, dont {n_sec1} avec section='1'")
            await asyncio.sleep(DELAI_S)

    print("\n\n========== SYNTHÈSE GLOBALE ==========")
    print(f"\nValeurs distinctes du champ 'section' (sur toutes les lignes) :")
    for k, n in counter_section.most_common():
        print(f"  {k!r:12s} → {n}")
    print(f"\nPrésence du champ 'section' : {dict(presence_section)}")

    total_lignes = sum(par_commande_total_lignes.values())
    total_sec1   = sum(par_commande_section_1_n.values())
    nb_commandes_avec_intitule = sum(1 for n in par_commande_section_1_n.values() if n > 0)
    print(f"\nTotal lignes inspectées : {total_lignes}")
    print(f"Total lignes section='1' : {total_sec1}")
    print(f"Commandes ayant ≥1 intitulé : {nb_commandes_avec_intitule}/{len(par_commande_total_lignes)}")

    print("\nDétail par commande :")
    for kdoc, ref, _ in SAMPLE:
        n = par_commande_section_1_n.get(kdoc, "—")
        t = par_commande_total_lignes.get(kdoc, "—")
        print(f"  {ref:11s} (id={kdoc}) : {t} lignes, {n} en section='1'")

    print("\nÉchantillon visuel — 6 lignes section='1' tirées de commandes différentes :")
    seen = set()
    shown = 0
    for kdoc, ref, idx, title, id_prod, total in par_commande_section_1:
        if kdoc in seen and shown >= 4:
            continue
        seen.add(kdoc)
        print(f"  [{ref}] ligne#{idx} title={title!r} id_product={id_prod} total={total}")
        shown += 1
        if shown >= 6:
            break

    print(f"\n=== Faux négatifs œil (titres MAJ + id_product=0 + montants=0 mais section != '1') : "
          f"{len(faux_negatifs_oeil)} ===")
    for kdoc, ref, idx, sec, title, id_prod, total in faux_negatifs_oeil[:10]:
        print(f"  [{ref}] ligne#{idx} section={sec!r} title={title!r} id_product={id_prod} total={total}")


asyncio.run(main())
