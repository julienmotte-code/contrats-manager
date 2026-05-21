"""
Script de diagnostic Karlia — LECTURE SEULE
Identifie les valeurs de id_status utilisées par Karlia pour les différents
statuts de factures.

Aucune création, aucune modification — uniquement GET.

Usage :
  docker compose exec backend python -m app.scripts.diag_karlia_statuts
"""
import asyncio
import sys
from collections import defaultdict

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.models import Parametre
from app.services.karlia_service import KarliaService


async def main():
    db = SessionLocal()
    p = db.query(Parametre).filter(Parametre.cle == "karlia_api_key").first()
    if not p or not p.valeur:
        print("ERREUR : aucune clé karlia_api_key en base")
        db.close()
        sys.exit(1)
    settings.KARLIA_API_KEY = p.valeur
    db.close()

    karlia = KarliaService()

    # NB: Karlia v2 v2 attend `type` (pas `id_type` qui est silencieusement ignoré)
    # — vu dans karlia_devis_service.py:148
    print("\n=== Récupération des FACTURES (type=4) — limit 200 ===\n")
    result = await karlia._get("/documents", {"type": 4, "limit": 200})
    docs = result.get("data", [])
    total = result.get("pagination", {}).get("total", "?")
    print(f"Factures récupérées : {len(docs)} (total Karlia : {total})\n")

    groupes = defaultdict(list)
    for d in docs:
        cle = (d.get("id_type"), d.get("id_status"))
        groupes[cle].append(d)

    print("=== Synthèse par (id_type, id_status) ===\n")
    header = (
        f"{'id_type':<10} {'id_status':<12} {'count':<8} "
        f"{'exemple_ref':<25} {'exemple_number':<20} autres_champs_statut"
    )
    print(header)
    print("-" * 140)
    for (id_type, id_status), liste in sorted(
        groupes.items(), key=lambda x: (str(x[0][0]), str(x[0][1]))
    ):
        ex = liste[0]
        autres = {}
        for k in ["status", "status_name", "draft", "is_draft", "state", "type", "type_name"]:
            if k in ex:
                autres[k] = ex[k]
        print(
            f"{str(id_type):<10} {str(id_status):<12} {len(liste):<8} "
            f"{str(ex.get('reference', ''))[:24]:<25} "
            f"{str(ex.get('number', ''))[:19]:<20} {autres}"
        )

    print("\n\n=== Détail complet du premier document de chaque groupe ===\n")
    for (id_type, id_status), liste in sorted(
        groupes.items(), key=lambda x: str(x[0][1])
    ):
        ex = liste[0]
        doc_id = ex.get("id")
        print(
            f"\n--- id_type={id_type}, id_status={id_status} "
            f"(doc {doc_id}, ref={ex.get('reference')}, number={ex.get('number')}) ---"
        )
        try:
            detail = await karlia._get(f"/documents/{doc_id}")
            for k in sorted(detail.keys()):
                v = detail[k]
                if any(kw in k.lower() for kw in ["status", "draft", "type", "state", "number", "reference"]):
                    print(f"  {k} = {v}")
        except Exception as e:
            print(f"  Erreur GET détail : {e}")
        # Pause pour rester sous le quota (100 req/min)
        await asyncio.sleep(0.8)

    print("\n\n=== Fin du diagnostic ===")


if __name__ == "__main__":
    asyncio.run(main())
