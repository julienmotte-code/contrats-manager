"""
Tests — facturation par lignes (backend), version MONO-COMMANDE (v3.5.0).

À exécuter DANS le conteneur backend :
    docker compose cp /tmp/test_facturer_lignes.py backend:/tmp/test_facturer_lignes.py
    docker compose exec -T -e PYTHONPATH=/app backend python /tmp/test_facturer_lignes.py

AUCUNE émission Karlia réelle : karlia.creer_facture est MOCKÉ.
"""
import asyncio
import sys

from app.core.database import SessionLocal
from app.models.models import CommandeLigne
from app.services.routage_service import DESTINATION_FACTURATION_DIRECTE
import app.api.commandes as cmd_api
from app.api.commandes import (
    get_lignes_a_facturer,
    facturer_lignes,
    FacturerLignesPayload,
)
from fastapi import HTTPException

INTITULES_REPEUPLES = {1042, 1043, 1045, 1047}  # BC26-0090, section_karlia=1

ok = 0
ko = 0


def check(label, cond):
    global ok, ko
    if cond:
        ok += 1
        print(f"  [OK] {label}")
    else:
        ko += 1
        print(f"  [KO] {label}")


async def main():
    db = SessionLocal()
    try:
        # ── Test 1 : liste — intitulés section_karlia=1 exclus ──────────────
        print("\n== Test 1 : GET lignes-a-facturer exclut les intitulés (section=1) ==")
        res = await get_lignes_a_facturer(page=1, page_size=1000, search=None, db=db, current_user=None)
        ids_listes = {it.ligne_id for it in res.items}
        print(f"  total lignes à facturer = {res.total}")
        check("aucun intitulé repeuplé (1042/1043/1045/1047) dans la liste",
              ids_listes.isdisjoint(INTITULES_REPEUPLES))
        # Invariant : la liste ne contient QUE des lignes section NULL ou 0.
        sections = {db.query(CommandeLigne).get(i).section_karlia for i in ids_listes}
        check(f"sections présentes ⊆ {{None, 0}} (vu : {sections})",
              sections.issubset({None, 0}))

        # Regrouper par commande pour les tests suivants.
        by_cmd = {}
        for it in res.items:
            by_cmd.setdefault(it.commande_id, []).append(it)

        # ── Test 2 : mono-commande — 2 commandes différentes → 400 ──────────
        print("\n== Test 2 : sélection multi-commandes refusée (mono-commande) ==")
        cmds = list(by_cmd.keys())
        if len(cmds) >= 2:
            sel = [by_cmd[cmds[0]][0].ligne_id, by_cmd[cmds[1]][0].ligne_id]
            try:
                await facturer_lignes(FacturerLignesPayload(ligne_ids=sel), db=db, current_user=None)
                check("multi-commandes rejeté (400)", False)
            except HTTPException as e:
                msg = str(e.detail)
                check(f"multi-commandes rejeté (400) — {e.status_code}: {msg[:55]}",
                      e.status_code == 400 and "une seule commande" in msg)
        else:
            print("  [SKIP] moins de 2 commandes dans la liste")

        # ── Test 3 : ligne déjà facturée → 400 ──────────────────────────────
        print("\n== Test 3 : ligne déjà facturée refusée ==")
        if res.items:
            cible = res.items[0].ligne_id
            ligne = db.query(CommandeLigne).get(cible)
            ligne.facture_karlia_id = "TEST-DEJA-FACTUREE"
            db.flush()
            try:
                await facturer_lignes(FacturerLignesPayload(ligne_ids=[cible]), db=db, current_user=None)
                check("ligne déjà facturée rejetée (400)", False)
            except HTTPException as e:
                check(f"ligne déjà facturée rejetée (400) — {e.status_code}", e.status_code == 400)
            finally:
                db.rollback()

        # ── Test 4 : destination invalide (contrat) → 400 ───────────────────
        print("\n== Test 4 : destination non-facturation_directe refusée ==")
        ligne_contrat = (db.query(CommandeLigne)
                         .filter(CommandeLigne.destination == "contrat")
                         .first())
        if ligne_contrat:
            try:
                await facturer_lignes(FacturerLignesPayload(ligne_ids=[ligne_contrat.id]), db=db, current_user=None)
                check("ligne 'contrat' rejetée (400)", False)
            except HTTPException as e:
                check(f"ligne 'contrat' rejetée (400) — {e.status_code}", e.status_code == 400)
        else:
            print("  [SKIP] aucune ligne 'contrat'")

        # ── Test 5 : sélection vide → 400 ───────────────────────────────────
        print("\n== Test 5 : sélection vide refusée ==")
        try:
            await facturer_lignes(FacturerLignesPayload(ligne_ids=[]), db=db, current_user=None)
            check("sélection vide rejetée (400)", False)
        except HTTPException as e:
            check(f"sélection vide rejetée (400) — {e.status_code}", e.status_code == 400)

        # ── Test 6 : ligne inexistante → 404 ────────────────────────────────
        print("\n== Test 6 : ligne inexistante refusée ==")
        try:
            await facturer_lignes(FacturerLignesPayload(ligne_ids=[999999999]), db=db, current_user=None)
            check("ligne inexistante rejetée (404)", False)
        except HTTPException as e:
            check(f"ligne inexistante rejetée (404) — {e.status_code}", e.status_code == 404)

        # ── Test 7 : nominal mono-commande + id_opportunity passé (MOCK) ────
        print("\n== Test 7 : chemin nominal 1 commande, id_opportunity transmis (Karlia MOCKÉ) ==")
        appels = {}

        async def fake_creer_facture(client_karlia_id, lignes, reference_contrat,
                                     date_echeance, montant_ht, description="", id_opportunity=None):
            appels["client"] = client_karlia_id
            appels["nb_lignes"] = len(lignes)
            appels["id_opportunity"] = id_opportunity
            return {"id": "MOCK-DOC-123", "reference": "FAC-MOCK-001"}

        original = cmd_api.karlia.creer_facture
        cmd_api.karlia.creer_facture = fake_creer_facture
        try:
            # Une commande de la liste (toutes ses lignes = même commande, même client).
            cmd0 = max(by_cmd.keys(), key=lambda c: len(by_cmd[c])) if by_cmd else None
            if cmd0 is not None:
                sel = [it.ligne_id for it in by_cmd[cmd0]]
                from app.models.models import Commande
                cmd_obj = db.query(Commande).get(cmd0)
                opp_attendue = cmd_obj.karlia_opportunity_id
                r = await facturer_lignes(FacturerLignesPayload(ligne_ids=sel), db=db, current_user=None)
                check("facture_karlia_id == mock", r.facture_karlia_id == "MOCK-DOC-123")
                check(f"nb_lignes_facturees == {len(sel)}", r.nb_lignes_facturees == len(sel))
                check(f"id_opportunity transmis == commande.karlia_opportunity_id ({opp_attendue})",
                      appels.get("id_opportunity") == opp_attendue)
                # L'endpoint passe client_karlia_id=str(...) à creer_facture.
                check("appel Karlia mono-client", appels.get("client") == str(cmd_obj.karlia_customer_id))
                # Marquage en DB
                db.expire_all()
                marquees = (db.query(CommandeLigne)
                            .filter(CommandeLigne.id.in_(sel),
                                    CommandeLigne.facture_karlia_id == "MOCK-DOC-123")
                            .count())
                check(f"{len(sel)} lignes marquées en DB", marquees == len(sel))
                # Anti-doublon : refacturer → 400
                try:
                    await facturer_lignes(FacturerLignesPayload(ligne_ids=sel), db=db, current_user=None)
                    check("refacturation rejetée (400)", False)
                except HTTPException as e:
                    check(f"refacturation rejetée (400) — {e.status_code}", e.status_code == 400)
                # CLEANUP
                for lid in sel:
                    l = db.query(CommandeLigne).get(lid)
                    l.facture_karlia_id = None
                    l.facture_karlia_ref = None
                    l.date_facturee = None
                db.commit()
                print("  [CLEANUP] marquage de test annulé (lignes ré-éligibles)")
            else:
                print("  [SKIP] aucune commande exploitable")
        finally:
            cmd_api.karlia.creer_facture = original

    finally:
        db.close()

    print(f"\n===== RÉSULTAT : {ok} OK / {ko} KO =====")
    sys.exit(1 if ko else 0)


if __name__ == "__main__":
    asyncio.run(main())
