"""
Diagnostic LECTURE SEULE — structure des lignes Karlia pour BC26-0048.
Récupère karlia_api_key depuis la base, GET /documents/677632, dump COMPLET
des entrées products_list avec leurs clés et valeurs.
But : identifier un marqueur natif Karlia distinguant les lignes d'intitulé
des vraies lignes (champ 'section', 'optional', 'hide_in_pdf', etc.).
Rate-limit : un seul GET, pas de sleep nécessaire.
"""
import asyncio
import json
from typing import Any, Dict, List

import httpx

from app.core.database import SessionLocal
from app.models.models import Parametre

BASE = "https://karlia.fr/app/api/v2"
DOC_ID = 677632  # BC26-0048


def load_key() -> str:
    db = SessionLocal()
    try:
        p = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
        if not p or not p.valeur:
            raise SystemExit("Clé karlia_api_key absente.")
        return p.valeur
    finally:
        db.close()


async def main():
    key = load_key()
    print(f"Clé chargée (len={len(key)})")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(base_url=BASE, headers=headers, timeout=30.0) as cl:
        r = await cl.get(f"/documents/{DOC_ID}")
        print(f"GET /documents/{DOC_ID} → HTTP {r.status_code}")
        r.raise_for_status()
        data = r.json()

    plist: List[Dict[str, Any]] = data.get("products_list") or []
    print(f"\nProducts_list contient {len(plist)} entrées.")
    print(f"\nTop-level header keys (extrait) : "
          f"number={data.get('number')} id_status={data.get('id_status')} "
          f"status_text={data.get('status_text')} canceled={data.get('canceled')}")

    # Premier passage : afficher TOUTES les clés présentes dans CHAQUE entrée
    print("\n=== Clés présentes par entrée (pour repérer marqueur de type) ===")
    all_keys_seen = set()
    for i, p in enumerate(plist):
        all_keys_seen.update(p.keys())
    print(f"Union des clés vues : {sorted(all_keys_seen)}\n")

    # Pour chaque ligne : dump des champs "candidats marqueur de type"
    candidats_keys = [
        "id_product", "title", "description", "section", "optional",
        "hide_in_pdf", "id_unit", "unit", "type", "line_type",
        "is_title", "is_section", "is_comment",
        "quantity", "price_without_tax", "total_without_tax",
        "id_vat", "discount_percent", "chart_of_account",
        "progress_type", "progress_value", "progress_percent",
        "quantity_delivered", "reference",
    ]
    print("=== Dump par ligne (champs candidats marqueur de type) ===")
    for i, p in enumerate(plist):
        view = {k: p.get(k) for k in candidats_keys if k in p}
        # Tronquer description pour lisibilité
        if "description" in view and view["description"]:
            view["description"] = view["description"][:60] + ("..." if len(p["description"]) > 60 else "")
        if "title" in view and view["title"]:
            view["title"] = view["title"][:60] + ("..." if len(p["title"]) > 60 else "")
        print(f"\nLigne {i+1} (ordre {i}):")
        for k, v in view.items():
            print(f"  {k:25s} = {v!r}")

    # Synthèse : distribution de quelques champs susceptibles d'être marqueurs
    print("\n=== Synthèse marqueurs candidats ===")
    for key in ("section", "optional", "hide_in_pdf", "id_product", "id_unit",
                "progress_type", "chart_of_account"):
        vals = [p.get(key) for p in plist]
        distinct = {}
        for v in vals:
            distinct[str(v)] = distinct.get(str(v), 0) + 1
        print(f"  {key:20s} → {distinct}")

asyncio.run(main())
