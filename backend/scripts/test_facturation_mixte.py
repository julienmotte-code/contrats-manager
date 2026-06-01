"""
Test étape 1 — facturation mixte ligne + prestation.
    docker compose exec -T -e PYTHONPATH=/app backend python /tmp/test_facturation_mixte.py

Karlia MOCKÉ. Crée des prestations temporaires (réalisées) pour les tests, et
nettoie tout en fin de run (delete + unmark).
"""
import asyncio
import sys
from types import SimpleNamespace

from app.core.database import SessionLocal
from app.models.models import CommandeLigne, Commande, Prestation
import app.api.commandes as cmd_api
from app.api.commandes import (
    construire_ligne_karlia_depuis_prestation,
    ligne_facturable_pour_prestation,
    facturer_lignes,
    facturer_commande,
    get_lignes_a_facturer,
    FacturerElementsPayload,
    FacturerElementItem,
)
from fastapi import HTTPException

ADMIN = SimpleNamespace(role="ADMIN", formateur_id=None)
ok = 0
ko = 0


def check(label, cond):
    global ok, ko
    ok += 1 if cond else 0
    ko += 0 if cond else 1
    print(f"  [{'OK' if cond else 'KO'}] {label}")


def ns(**kw):
    return SimpleNamespace(**kw)


async def main():
    # ── Unitaire : construire_ligne_karlia_depuis_prestation + facturable ───
    print("\n== unitaires helpers prestation ==")
    ligne = ns(quantite=2, montant_ht=937.50, prix_unitaire_ht=1250, taux_tva=20,
               karlia_product_id="500227", designation="Formation", section_karlia=0, destination="a_planifier")
    p = ns(id=1, commande_ligne=ligne, designation="Formation J1")
    d = construire_ligne_karlia_depuis_prestation(p)
    check(f"prestation unit_price = montant_ht/qte = 468.75 (got {d['unit_price']})", d["unit_price"] == 468.75)
    check("prestation quantity = 1", d["quantity"] == 1.0)
    check("description = celle de la prestation", d["description"] == "Formation J1")

    check("facturable : ligne valide", ligne_facturable_pour_prestation(ligne) is True)
    check("non facturable : commande_ligne None", ligne_facturable_pour_prestation(None) is False)
    check("non facturable : intitulé section=1",
          ligne_facturable_pour_prestation(ns(section_karlia=1, destination="x", karlia_product_id="5", montant_ht=100)) is False)
    check("non facturable : produit '0'",
          ligne_facturable_pour_prestation(ns(section_karlia=0, destination="a_planifier", karlia_product_id="0", montant_ht=100)) is False)
    check("non facturable : montant 0",
          ligne_facturable_pour_prestation(ns(section_karlia=0, destination="a_planifier", karlia_product_id="5", montant_ht=0)) is False)
    try:
        construire_ligne_karlia_depuis_prestation(ns(id=9, commande_ligne=None))
        check("prestation sans ligne -> ValueError", False)
    except ValueError:
        check("prestation sans ligne -> ValueError", True)

    # ── Mock Karlia ─────────────────────────────────────────────────────────
    captured = {}

    async def fake_creer_facture(client_karlia_id, lignes, reference_contrat,
                                 date_echeance, montant_ht, description="", id_opportunity=None):
        captured["lignes"] = lignes
        captured["id_opportunity"] = id_opportunity
        return {"id": "MOCK-DOC", "reference": "FAC-MOCK"}

    original = cmd_api.karlia.creer_facture
    cmd_api.karlia.creer_facture = fake_creer_facture
    db = SessionLocal()
    temp_ids = []
    touched_lignes = []

    def unmark_ligne(lid):
        l = db.query(CommandeLigne).get(lid)
        if l:
            l.facture_karlia_id = None; l.facture_karlia_ref = None; l.date_facturee = None

    try:
        # ── Liste unifiée : type présent, prestations facturables seulement ─
        print("\n== liste unifiée ==")
        res = await get_lignes_a_facturer(page=1, page_size=1000, search=None, db=db, current_user=ADMIN)
        types = {it.type for it in res.items}
        check(f"items typés (types vus : {types or '∅'})", types.issubset({"ligne", "prestation"}))
        nb_prest = sum(1 for it in res.items if it.type == "prestation")
        print(f"  total={res.total}, dont prestations={nb_prest} (prestation 19 sur ligne invalide doit être exclue)")
        check("prestation 19 (ligne prix0/produit0) exclue de la liste",
              not any(it.type == "prestation" and it.id == 19 for it in res.items))

        # ── Préparer une prestation réalisée sur une ligne SGI facturable ───
        ligne_sgi = (db.query(CommandeLigne)
                     .filter(CommandeLigne.destination == "a_planifier",
                             CommandeLigne.karlia_product_id.isnot(None),
                             CommandeLigne.montant_ht > 0).first())
        cmd = db.query(Commande).get(ligne_sgi.commande_id)
        P = Prestation(commande_id=cmd.id, commande_ligne_id=ligne_sgi.id,
                       designation="TEST prestation réalisée", statut="realisee")
        db.add(P); db.commit(); temp_ids.append(P.id)
        attendu_unit = round(float(ligne_sgi.montant_ht) / float(ligne_sgi.quantite or 1), 2)

        # ── Facturer 1 prestation seule ─────────────────────────────────────
        print("\n== facturer 1 prestation seule ==")
        captured.clear()
        r = await facturer_lignes(FacturerElementsPayload(
            elements=[FacturerElementItem(type="prestation", id=P.id)]), db=db, current_user=ADMIN)
        check(f"unit_price = montant_ht/qte = {attendu_unit} (got {captured['lignes'][0]['unit_price']})",
              captured["lignes"][0]["unit_price"] == attendu_unit)
        db.expire_all()
        check("prestation marquée facturée", db.query(Prestation).get(P.id).facture_karlia_id == "MOCK-DOC")
        check("id_opportunity transmis", captured["id_opportunity"] == cmd.karlia_opportunity_id)
        # unmark pour réutiliser P
        db.query(Prestation).get(P.id).facture_karlia_id = None
        db.query(Prestation).get(P.id).facture_karlia_ref = None
        db.query(Prestation).get(P.id).date_facturee = None
        db.commit()

        # ── Facturer 1 ligne facturation_directe seule ──────────────────────
        print("\n== facturer 1 ligne seule ==")
        ligne_fd = (db.query(CommandeLigne)
                    .filter(CommandeLigne.destination == "facturation_directe",
                            CommandeLigne.facture_karlia_id.is_(None),
                            CommandeLigne.commande_id == cmd.id).first())
        if ligne_fd:
            captured.clear()
            await facturer_lignes(FacturerElementsPayload(
                elements=[FacturerElementItem(type="ligne", id=ligne_fd.id)]), db=db, current_user=ADMIN)
            touched_lignes.append(ligne_fd.id)
            db.expire_all()
            check("ligne marquée facturée", db.query(CommandeLigne).get(ligne_fd.id).facture_karlia_id == "MOCK-DOC")
            unmark_ligne(ligne_fd.id); db.commit()
        else:
            print(f"  [SKIP] pas de ligne facturation_directe sur commande {cmd.id}")

        # ── Mixte : 1 ligne + 1 prestation de la MÊME commande ──────────────
        print("\n== mixte ligne + prestation (même commande) ==")
        if ligne_fd:
            captured.clear()
            r = await facturer_lignes(FacturerElementsPayload(elements=[
                FacturerElementItem(type="ligne", id=ligne_fd.id),
                FacturerElementItem(type="prestation", id=P.id),
            ]), db=db, current_user=ADMIN)
            check("products_list contient 2 éléments", len(captured["lignes"]) == 2)
            check("nb_elements_factures == 2", r.nb_elements_factures == 2)
            db.expire_all()
            check("ligne marquée", db.query(CommandeLigne).get(ligne_fd.id).facture_karlia_id == "MOCK-DOC")
            check("prestation marquée", db.query(Prestation).get(P.id).facture_karlia_id == "MOCK-DOC")
            # cleanup marquages
            unmark_ligne(ligne_fd.id)
            pp = db.query(Prestation).get(P.id)
            pp.facture_karlia_id = None; pp.facture_karlia_ref = None; pp.date_facturee = None
            db.commit()
        else:
            print("  [SKIP] mixte non testable (pas de ligne FD même commande)")

        # ── Mono-commande violé ─────────────────────────────────────────────
        print("\n== mono-commande violé ==")
        autre = (db.query(CommandeLigne)
                 .filter(CommandeLigne.destination == "facturation_directe",
                         CommandeLigne.facture_karlia_id.is_(None),
                         CommandeLigne.commande_id != cmd.id).first())
        if ligne_fd and autre:
            try:
                await facturer_lignes(FacturerElementsPayload(elements=[
                    FacturerElementItem(type="ligne", id=ligne_fd.id),
                    FacturerElementItem(type="ligne", id=autre.id)]), db=db, current_user=ADMIN)
                check("multi-commandes -> 400", False)
            except HTTPException as e:
                check(f"multi-commandes -> 400 (got {e.status_code})", e.status_code == 400)
        else:
            print("  [SKIP] pas 2 commandes distinctes disponibles")

        # ── Prestation sur ligne prix0/produit invalide (id 19) -> 400 ──────
        print("\n== prestation sur ligne invalide -> 400 ==")
        p19 = db.query(Prestation).get(19)
        if p19 and p19.statut == "realisee":
            try:
                await facturer_lignes(FacturerElementsPayload(
                    elements=[FacturerElementItem(type="prestation", id=19)]), db=db, current_user=ADMIN)
                check("prestation ligne invalide -> 400", False)
            except HTTPException as e:
                check(f"prestation ligne invalide -> 400 (got {e.status_code})", e.status_code == 400)
        else:
            print("  [SKIP] prestation 19 absente/non réalisée")

        # ── Prestation sur ligne intitulé (section=1) -> 400 ────────────────
        print("\n== prestation sur ligne intitulé -> 400 ==")
        ligne_int = db.query(CommandeLigne).filter(CommandeLigne.section_karlia == 1).first()
        if ligne_int:
            P3 = Prestation(commande_id=ligne_int.commande_id, commande_ligne_id=ligne_int.id,
                            designation="TEST intitulé", statut="realisee")
            db.add(P3); db.commit(); temp_ids.append(P3.id)
            try:
                await facturer_lignes(FacturerElementsPayload(
                    elements=[FacturerElementItem(type="prestation", id=P3.id)]), db=db, current_user=ADMIN)
                check("prestation intitulé -> 400", False)
            except HTTPException as e:
                check(f"prestation intitulé -> 400 (got {e.status_code})", e.status_code == 400)
        else:
            print("  [SKIP] pas de ligne intitulé")

        # ── Prestation sans commande_ligne -> 400 ───────────────────────────
        print("\n== prestation sans commande_ligne -> 400 ==")
        P2 = Prestation(commande_id=cmd.id, commande_ligne_id=None,
                        designation="TEST sans ligne", statut="realisee")
        db.add(P2); db.commit(); temp_ids.append(P2.id)
        try:
            await facturer_lignes(FacturerElementsPayload(
                elements=[FacturerElementItem(type="prestation", id=P2.id)]), db=db, current_user=ADMIN)
            check("prestation sans ligne -> 400", False)
        except HTTPException as e:
            check(f"prestation sans ligne -> 400 (got {e.status_code})", e.status_code == 400)

        # ── facturer_commande 409 si élément déjà facturé ───────────────────
        print("\n== facturer_commande -> 409 si élément déjà facturé ==")
        cmd_dep = db.query(Commande).filter(Commande.statut == "deployee").first()
        if cmd_dep:
            l0 = db.query(CommandeLigne).filter(CommandeLigne.commande_id == cmd_dep.id).first()
            l0.facture_karlia_id = "MARK-409"; db.commit(); touched_lignes.append(l0.id)
            try:
                await facturer_commande(cmd_dep.id, db=db, current_user=ADMIN)
                check("facturer_commande -> 409", False)
            except HTTPException as e:
                check(f"facturer_commande -> 409 (got {e.status_code})", e.status_code == 409)
            unmark_ligne(l0.id); db.commit()
        else:
            print("  [SKIP] pas de commande deployee")

        # ── realiser ne touche plus commande.statut ─────────────────────────
        print("\n== realiser ne bascule plus commande.statut ==")
        from app.api.prestations import realiser_prestation
        pl = db.query(Prestation).filter(Prestation.statut == "planifiee").first()
        if pl:
            cmd_av = db.query(Commande).get(pl.commande_id)
            statut_av = cmd_av.statut
            pid = pl.id
            await realiser_prestation(pid, db=db, current_user=ADMIN)
            db.expire_all()
            check(f"commande statut inchangé ('{statut_av}')",
                  db.query(Commande).get(cmd_av.id).statut == statut_av)
            # revert prestation -> planifiee
            db.query(Prestation).get(pid).statut = "planifiee"
            db.commit()
        else:
            print("  [SKIP] pas de prestation planifiee")

    finally:
        cmd_api.karlia.creer_facture = original
        # CLEANUP : delete prestations temp + unmark lignes touchées
        for lid in touched_lignes:
            unmark_ligne(lid)
        for tid in temp_ids:
            t = db.query(Prestation).get(tid)
            if t:
                db.delete(t)
        db.commit()
        print(f"  [CLEANUP] {len(temp_ids)} prestation(s) temp supprimée(s), lignes démarquées")
        db.close()

    print(f"\n===== RÉSULTAT : {ok} OK / {ko} KO =====")
    sys.exit(1 if ko else 0)


if __name__ == "__main__":
    asyncio.run(main())
