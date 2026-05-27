"""
Resync ciblée des commandes au statut 'nouvelle' depuis Karlia.

Re-fetch GET /documents/{id} commande par commande, puis appel direct à
karlia_devis_service._update_commande pour réécrire id_product_category,
product_category et section_karlia sur les lignes (suppression / réinsertion).

LECTURE SEULE côté Karlia : pas de marquage 'Traité', pas de POST.
Transaction par commande (commit fait par _update_commande, rollback en cas
d'erreur). On loggue chaque échec et on continue.

Usage :
  docker compose exec -T -e PYTHONPATH=/app backend python3 /tmp/resync_ciblee.py
"""
import asyncio
import logging
from collections import Counter
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.models import Commande, CommandeLigne
from app.services.karlia_devis_service import karlia_devis_service
from app.services.routage_service import (
    destination_par_defaut,
    DESTINATION_A_PLANIFIER,
    DESTINATION_CONTRAT,
    DESTINATION_FACTURATION_DIRECTE,
    DESTINATION_INTITULE,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("resync_ciblee")

SLEEP_SEC = 1.0


async def resync():
    db: Session = SessionLocal()
    succes: List[Tuple[str, int, int]] = []  # (ref, id, nb_lignes_apres)
    echecs: List[Tuple[str, int, str]] = []  # (ref, id, error)

    sections_counter: Counter = Counter()
    destinations_counter: Counter = Counter()
    total_lignes_reecrites = 0
    skipped_no_doc = 0

    try:
        commandes = (
            db.query(Commande)
            .filter(Commande.statut == "nouvelle")
            .order_by(Commande.id)
            .all()
        )
        logger.info(
            f"{len(commandes)} commandes 'nouvelle' à resync "
            f"(sleep={SLEEP_SEC}s entre BC)."
        )

        # Index unique pour toute la passe : évite N appels à la DB articles_cache.
        articles_cat_index = karlia_devis_service._build_articles_categorie_index(db)
        logger.info(f"Index catégories articles_cache : {len(articles_cat_index)} entrées.")

        for idx, commande in enumerate(commandes, start=1):
            ref = commande.reference_devis or f"id={commande.id}"
            karlia_doc_id = commande.karlia_document_id

            if not karlia_doc_id:
                logger.warning(f"[{ref}] karlia_document_id NULL — skip.")
                skipped_no_doc += 1
                continue

            await asyncio.sleep(SLEEP_SEC)
            try:
                # Appel direct à _update_commande : il fait son propre re-fetch
                # via get_devis_detail(devis_data["id"]) puis régénère les
                # lignes avec id_product_category / product_category /
                # section_karlia, et commit.
                # On lui passe juste {"id": ...} : _update_commande complétera
                # le dict avec bc_detail (products_list, etc.).
                await karlia_devis_service._update_commande(
                    db,
                    commande,
                    {"id": karlia_doc_id},
                    client_cache_mem=None,
                    articles_cat_index=articles_cat_index,
                )
            except Exception as e:
                db.rollback()
                echecs.append((ref, commande.id, repr(e)))
                logger.error(f"[{ref}] échec resync : {e!r}")
                continue

            # Re-lire les lignes pour le récap
            db.refresh(commande)
            nb_lignes = 0
            for ligne in commande.lignes:
                nb_lignes += 1
                # section_karlia
                if ligne.section_karlia is None:
                    sections_counter["NULL"] += 1
                else:
                    sections_counter[str(ligne.section_karlia)] += 1
                # destination_defaut recalculée
                dest = destination_par_defaut(
                    ligne.id_product_category,
                    ligne.product_category,
                    section=ligne.section_karlia,
                )
                destinations_counter[dest] += 1

            total_lignes_reecrites += nb_lignes
            succes.append((ref, commande.id, nb_lignes))

            if idx % 10 == 0:
                logger.info(
                    f"Progression : {idx}/{len(commandes)} traitées "
                    f"({len(succes)} OK, {len(echecs)} échecs, "
                    f"{total_lignes_reecrites} lignes réécrites)"
                )

        # ─── Récap final ─────────────────────────────────────────────────
        print()
        print("=" * 90)
        print("RESYNC CIBLÉE — RÉCAP")
        print("=" * 90)
        print(f"Commandes traitées avec succès : {len(succes)}")
        print(f"Commandes en échec             : {len(echecs)}")
        print(f"Commandes sans karlia_document_id : {skipped_no_doc}")
        print(f"Total lignes réécrites         : {total_lignes_reecrites}")
        print()
        print("section_karlia (sur les lignes réécrites) :")
        for val, n in sorted(sections_counter.items()):
            print(f"  {val:>6} : {n:>5}")
        print()
        print("destination_defaut (recalculée sur les lignes réécrites) :")
        for dest in (DESTINATION_A_PLANIFIER, DESTINATION_CONTRAT,
                     DESTINATION_FACTURATION_DIRECTE, DESTINATION_INTITULE):
            print(f"  {dest:<22} : {destinations_counter.get(dest, 0):>5}")
        print()
        if echecs:
            print("ÉCHECS détaillés :")
            for ref, cid, err in echecs:
                print(f"  - {ref} (id={cid}) : {err}")
        else:
            print(">>> Aucun échec.")
        print("=" * 90)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(resync())
