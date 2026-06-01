"""
Test — remise transmise à Karlia (construire_ligne_karlia + les 2 endpoints).
    docker compose exec -T -e PYTHONPATH=/app backend python /tmp/test_remise.py

Karlia MOCKÉ (aucune émission réelle). Nettoyage des marquages en fin de test.
"""
import asyncio
import sys
from types import SimpleNamespace

from app.core.database import SessionLocal
from app.models.models import CommandeLigne, Commande
import app.api.commandes as cmd_api
from app.api.commandes import (
    construire_ligne_karlia,
    facturer_lignes,
    facturer_commande,
    FacturerLignesPayload,
)

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


def ligne(quantite, montant_ht, prix_unitaire_ht, tva=20, kp="500227", desig="X"):
    return SimpleNamespace(
        quantite=quantite, montant_ht=montant_ht, prix_unitaire_ht=prix_unitaire_ht,
        taux_tva=tva, karlia_product_id=kp, designation=desig,
    )


async def main():
    # ── Tests unitaires construire_ligne_karlia ─────────────────────────────
    print("\n== construire_ligne_karlia ==")
    # remise : brut 1250 x2 mais montant 937.50 -> unit_price 468.75
    r = construire_ligne_karlia(ligne(2, 937.50, 1250))
    check(f"remise -> unit_price 468.75 (got {r['unit_price']})", r["unit_price"] == 468.75)
    check("quantity conservée = 2", r["quantity"] == 2.0)
    check("n'utilise PAS le brut (1250)", r["unit_price"] != 1250)
    check("clés Karlia présentes", set(r) == {"id_product", "quantity", "unit_price", "vat_rate", "description"})

    # pas de remise : brut 500 x2, montant 1000 -> unit_price 500 (= brut), pas de régression
    r = construire_ligne_karlia(ligne(2, 1000, 500))
    check(f"sans remise -> unit_price 500 (got {r['unit_price']})", r["unit_price"] == 500.0)

    # quantité 1 -> unit_price = montant_ht
    r = construire_ligne_karlia(ligne(1, 937.50, 1250))
    check(f"qte 1 -> unit_price = montant_ht 937.50 (got {r['unit_price']})", r["unit_price"] == 937.50)

    # quantité décimale 2.5 : montant 781.25 / 2.5 = 312.50
    r = construire_ligne_karlia(ligne(2.5, 781.25, 9999))
    check(f"qte 2.5 -> 312.50 (got {r['unit_price']})", r["unit_price"] == 312.50)

    # quantité 0 -> fallback 1, pas de division par zéro
    r = construire_ligne_karlia(ligne(0, 400, 400))
    check(f"qte 0 -> fallback, unit_price 400 (got {r['unit_price']})", r["unit_price"] == 400.0)
    # quantité None -> fallback 1
    r = construire_ligne_karlia(ligne(None, 250, 250))
    check(f"qte None -> fallback, unit_price 250 (got {r['unit_price']})", r["unit_price"] == 250.0)

    # arrondi 2 décimales : montant 100 / 3 = 33.33
    r = construire_ligne_karlia(ligne(3, 100, 40))
    check(f"arrondi 2 déc -> 33.33 (got {r['unit_price']})", r["unit_price"] == 33.33)

    # ── Mock Karlia commun aux 2 endpoints ──────────────────────────────────
    captured = {}

    async def fake_creer_facture(client_karlia_id, lignes, reference_contrat,
                                 date_echeance, montant_ht, description="", id_opportunity=None):
        captured["lignes"] = lignes
        return {"id": "MOCK-DOC", "reference": "FAC-MOCK"}

    original = cmd_api.karlia.creer_facture
    cmd_api.karlia.creer_facture = fake_creer_facture
    db = SessionLocal()
    try:
        # ── Endpoint 1 : facturer-lignes ────────────────────────────────────
        print("\n== facturer-lignes (endpoint) ==")
        cible = (db.query(CommandeLigne)
                 .filter(CommandeLigne.destination == "facturation_directe",
                         CommandeLigne.facture_karlia_id.is_(None))
                 .join(Commande, Commande.id == CommandeLigne.commande_id)
                 .filter(Commande.karlia_customer_id.isnot(None))
                 .first())
        if cible:
            attendu = round(float(cible.montant_ht or 0) / float(cible.quantite or 1), 2)
            captured.clear()
            await facturer_lignes(FacturerLignesPayload(ligne_ids=[cible.id]), db=db, current_user=None)
            l0 = captured["lignes"][0]
            check(f"facturer-lignes: unit_price = montant_ht/qte = {attendu} (got {l0['unit_price']})",
                  l0["unit_price"] == attendu)
            check("facturer-lignes: pas le brut", l0["unit_price"] != float(cible.prix_unitaire_ht or 0)
                  or float(cible.prix_unitaire_ht or 0) * float(cible.quantite or 1) == float(cible.montant_ht or 0))
            # cleanup : retirer le marquage posé par l'endpoint
            db.expire_all()
            cl = db.query(CommandeLigne).get(cible.id)
            cl.facture_karlia_id = None
            cl.facture_karlia_ref = None
            cl.date_facturee = None
            db.commit()
            print("  [CLEANUP] marquage facturer-lignes annulé")
        else:
            print("  [SKIP] aucune ligne facturation_directe éligible")

        # ── Endpoint 2 : facturer_commande ──────────────────────────────────
        print("\n== facturer_commande (endpoint) ==")
        cmd = db.query(Commande).filter(Commande.statut == "deployee",
                                        Commande.karlia_customer_id.isnot(None)).first()
        if cmd:
            cmd_id = cmd.id
            statut_avant = cmd.statut
            captured.clear()
            await facturer_commande(cmd_id, db=db, current_user=None)
            lignes_cap = captured["lignes"]
            # Recalcule l'attendu pour chaque ligne facturable de la commande
            db.expire_all()
            cmd2 = db.query(Commande).get(cmd_id)
            sources = [l for l in cmd2.lignes if not (l.section_karlia == 1 or l.destination == "intitule")]
            attendus = [round(float(l.montant_ht or 0) / float(l.quantite or 1), 2) for l in sources]
            gots = [l["unit_price"] for l in lignes_cap]
            check(f"facturer_commande: {len(gots)} lignes, unit_price tous = montant_ht/qte",
                  sorted(gots) == sorted(attendus) and len(gots) == len(attendus))
            # cleanup : restaurer la commande (l'endpoint l'a passée à 'facturee')
            cmd2.statut = statut_avant
            cmd2.facture_karlia_id = None
            cmd2.facture_karlia_ref = None
            db.commit()
            print(f"  [CLEANUP] commande {cmd_id} restaurée en '{statut_avant}'")
        else:
            print("  [SKIP] aucune commande deployee éligible")
    finally:
        cmd_api.karlia.creer_facture = original
        db.close()

    print(f"\n===== RÉSULTAT : {ok} OK / {ko} KO =====")
    sys.exit(1 if ko else 0)


if __name__ == "__main__":
    asyncio.run(main())
