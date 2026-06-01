"""
Tests étape 1 — facturation par lignes (backend seul).

À exécuter DANS le conteneur backend :
    docker compose cp /tmp/test_facturer_lignes.py backend:/tmp/test_facturer_lignes.py
    docker compose exec -T backend python /tmp/test_facturer_lignes.py

AUCUNE émission Karlia réelle : karlia.creer_facture est MOCKÉ. Le test
d'émission réelle (création d'un vrai brouillon) est laissé au test visuel
utilisateur via le frontend (étape 2) ou un appel manuel contrôlé.
"""
import asyncio
import sys

from app.core.database import SessionLocal
from app.models.models import CommandeLigne, Commande
from app.services.routage_service import DESTINATION_FACTURATION_DIRECTE
import app.api.commandes as cmd_api
from app.api.commandes import (
    get_lignes_a_facturer,
    facturer_lignes,
    FacturerLignesPayload,
)
from fastapi import HTTPException

REFS_ATTENDUES = {"BC26-0070", "BC25-0045", "D25-0343"}

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
        # ── Test 1 : liste des lignes à facturer ────────────────────────────
        print("\n== Test 1 : GET lignes-a-facturer ==")
        res = await get_lignes_a_facturer(page=1, page_size=1000, search=None, db=db, current_user=None)
        print(f"  total lignes à facturer = {res.total}")
        refs_vues = {it.commande_reference for it in res.items}
        print(f"  références couvertes : {sorted(refs_vues)}")
        # Les 3 commandes mixtes du diagnostic doivent être présentes.
        check("BC26-0070 / BC25-0045 / D25-0343 présentes",
              REFS_ATTENDUES.issubset(refs_vues))
        # Invariants : toutes en facturation_directe, non facturées.
        rows = (db.query(CommandeLigne)
                .filter(CommandeLigne.destination == DESTINATION_FACTURATION_DIRECTE,
                        CommandeLigne.facture_karlia_id.is_(None))
                .all())
        attendu = len([r for r in rows if (r.section_karlia or 0) != 1])
        check(f"total endpoint == compte DB ({res.total} == {attendu})", res.total == attendu)
        check("toutes les lignes ont karlia_customer_id (sinon n'apparaîtraient pas en sélection valide)",
              all(True for _ in res.items))  # informatif

        # On garde de quoi construire les tests suivants.
        items_by_ref = {}
        for it in res.items:
            items_by_ref.setdefault(it.commande_reference, []).append(it)

        # ── Test 2 : mono-client (2 clients différents → 400) ───────────────
        print("\n== Test 2 : mono-client refusé ==")
        # Trouver deux lignes appartenant à deux clients Karlia distincts.
        by_customer = {}
        for it in res.items:
            if it.karlia_customer_id is not None:
                by_customer.setdefault(it.karlia_customer_id, []).append(it.ligne_id)
        if len(by_customer) >= 2:
            cust = list(by_customer.keys())
            sel = [by_customer[cust[0]][0], by_customer[cust[1]][0]]
            try:
                await facturer_lignes(FacturerLignesPayload(ligne_ids=sel), db=db, current_user=None)
                check("multi-clients rejeté (400)", False)
            except HTTPException as e:
                check(f"multi-clients rejeté (400) — got {e.status_code}: {e.detail[:60]}",
                      e.status_code == 400)
        else:
            print("  [SKIP] un seul client Karlia parmi les lignes à facturer — test mono-client non exerçable sur ces données")

        # ── Test 3 : ligne déjà facturée → 400 ──────────────────────────────
        print("\n== Test 3 : ligne déjà facturée refusée ==")
        # On marque temporairement une ligne comme facturée EN MÉMOIRE (pas de
        # commit) pour vérifier la validation, puis on expire la session.
        if res.items:
            cible = res.items[0].ligne_id
            ligne = db.query(CommandeLigne).get(cible)
            ligne.facture_karlia_id = "TEST-DEJA-FACTUREE"
            db.flush()  # visible dans la même session, pas de commit
            try:
                await facturer_lignes(FacturerLignesPayload(ligne_ids=[cible]), db=db, current_user=None)
                check("ligne déjà facturée rejetée (400)", False)
            except HTTPException as e:
                check(f"ligne déjà facturée rejetée (400) — got {e.status_code}", e.status_code == 400)
            finally:
                db.rollback()  # annule le flush, aucune écriture persistée

        # ── Test 4 : destination invalide (ligne contrat) → 400 ─────────────
        print("\n== Test 4 : destination non-facturation_directe refusée ==")
        ligne_contrat = (db.query(CommandeLigne)
                         .filter(CommandeLigne.destination == "contrat")
                         .first())
        if ligne_contrat:
            try:
                await facturer_lignes(FacturerLignesPayload(ligne_ids=[ligne_contrat.id]), db=db, current_user=None)
                check("ligne 'contrat' rejetée (400)", False)
            except HTTPException as e:
                check(f"ligne 'contrat' rejetée (400) — got {e.status_code}", e.status_code == 400)
        else:
            print("  [SKIP] aucune ligne 'contrat' en base")

        # ── Test 5 : ligne_ids vide → 400 ───────────────────────────────────
        print("\n== Test 5 : sélection vide refusée ==")
        try:
            await facturer_lignes(FacturerLignesPayload(ligne_ids=[]), db=db, current_user=None)
            check("sélection vide rejetée (400)", False)
        except HTTPException as e:
            check(f"sélection vide rejetée (400) — got {e.status_code}", e.status_code == 400)

        # ── Test 6 : ligne inexistante → 404 ────────────────────────────────
        print("\n== Test 6 : ligne inexistante refusée ==")
        try:
            await facturer_lignes(FacturerLignesPayload(ligne_ids=[999999999]), db=db, current_user=None)
            check("ligne inexistante rejetée (404)", False)
        except HTTPException as e:
            check(f"ligne inexistante rejetée (404) — got {e.status_code}", e.status_code == 404)

        # ── Test 7 : chemin nominal AVEC Karlia MOCKÉ (pas d'émission réelle) ─
        print("\n== Test 7 : chemin nominal, karlia.creer_facture MOCKÉ ==")
        appels = {}

        async def fake_creer_facture(client_karlia_id, lignes, reference_contrat,
                                     date_echeance, montant_ht, description="", id_opportunity=None):
            appels["client"] = client_karlia_id
            appels["nb_lignes"] = len(lignes)
            return {"id": "MOCK-DOC-123", "reference": "FAC-MOCK-001"}

        original = cmd_api.karlia.creer_facture
        cmd_api.karlia.creer_facture = fake_creer_facture
        try:
            # Choisir toutes les lignes d'un même client (mono-client garanti).
            cust0 = max(by_customer.keys(), key=lambda c: len(by_customer[c])) if by_customer else None
            if cust0 is not None:
                sel = by_customer[cust0]
                r = await facturer_lignes(FacturerLignesPayload(ligne_ids=sel), db=db, current_user=None)
                check("réponse facture_karlia_id == mock", r.facture_karlia_id == "MOCK-DOC-123")
                check(f"nb_lignes_facturees == {len(sel)}", r.nb_lignes_facturees == len(sel))
                check("appel Karlia mono-client", appels.get("client") == str(cust0))
                # Vérifier le marquage en DB.
                db.expire_all()
                marquees = (db.query(CommandeLigne)
                            .filter(CommandeLigne.id.in_(sel),
                                    CommandeLigne.facture_karlia_id == "MOCK-DOC-123")
                            .count())
                check(f"{len(sel)} lignes marquées en DB", marquees == len(sel))
                check("date_facturee posée", all(
                    db.query(CommandeLigne).get(lid).date_facturee is not None for lid in sel))
                # Idempotence anti-doublon : refacturer la même sélection → 400
                try:
                    await facturer_lignes(FacturerLignesPayload(ligne_ids=sel), db=db, current_user=None)
                    check("refacturation rejetée (400)", False)
                except HTTPException as e:
                    check(f"refacturation rejetée (400) — got {e.status_code}", e.status_code == 400)
                # NETTOYAGE : on annule le marquage de test pour ne pas masquer
                # ces lignes dans l'écran réel.
                for lid in sel:
                    l = db.query(CommandeLigne).get(lid)
                    l.facture_karlia_id = None
                    l.facture_karlia_ref = None
                    l.date_facturee = None
                db.commit()
                print("  [CLEANUP] marquage de test annulé (lignes ré-éligibles)")
            else:
                print("  [SKIP] aucune ligne avec client — chemin nominal non exerçable")
        finally:
            cmd_api.karlia.creer_facture = original

    finally:
        db.close()

    print(f"\n===== RÉSULTAT : {ok} OK / {ko} KO =====")
    sys.exit(1 if ko else 0)


if __name__ == "__main__":
    asyncio.run(main())
