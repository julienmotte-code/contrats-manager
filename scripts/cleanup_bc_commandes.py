"""
Cleanup BC commandes — suppression ciblée des bons de commande importés à tort.

Contexte : la synchro Karlia a rapatrié dans la table `commandes` à la fois des
devis acceptés (à conserver, préfixe `D`) et des bons de commande (à supprimer,
préfixe `BC`). Seuls les devis sont attendus dans cette table.

Prédicat : `reference_devis LIKE 'BC%'`

Sécurités :
- transaction unique, rollback automatique sur exception (re-raised)
- abort si compte initial != EXPECTED_COUNT (base a bougé depuis le diagnostic)
- abort si recompte intermédiaire des BC != EXPECTED_COUNT
- abort si nombre effectif de suppressions != EXPECTED_COUNT
- déliage préventif `prestations.commande_id = NULL` malgré le CASCADE
  (règle 5 — défense en profondeur)
"""
import sys
from app.core.database import SessionLocal
from sqlalchemy import text, bindparam

EXPECTED_COUNT = 66
IDS_FILE = "/tmp/deleted_bc_ids.txt"


def main():
    db = SessionLocal()
    try:
        # 1. Récupérer les IDs des BC
        ids = [row[0] for row in db.execute(
            text("SELECT id FROM commandes WHERE reference_devis LIKE 'BC%' ORDER BY id")
        ).all()]
        print(f"[1] IDs récupérés : {len(ids)}")

        # 2. Sanity check sur le compte initial
        if len(ids) != EXPECTED_COUNT:
            print(f"[ABORT] Attendu {EXPECTED_COUNT} BC, trouvé {len(ids)}.")
            db.rollback()
            sys.exit(2)

        # 3. Écrire la liste des IDs
        with open(IDS_FILE, "w") as f:
            for i in ids:
                f.write(f"{i}\n")
        print(f"[3] Liste des IDs écrite dans {IDS_FILE}")

        # 4. Délier prestations.commande_id (défense en profondeur)
        stmt_p = text(
            "UPDATE prestations SET commande_id = NULL WHERE commande_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        nb_prestations = db.execute(stmt_p, {"ids": ids}).rowcount
        print(f"[4] prestations déliées (UPDATE commande_id=NULL) : {nb_prestations}")

        # 5. DELETE FROM commande_lignes
        stmt_l = text(
            "DELETE FROM commande_lignes WHERE commande_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        nb_lignes = db.execute(stmt_l, {"ids": ids}).rowcount
        print(f"[5] commande_lignes supprimées : {nb_lignes}")

        # 6. Recompte des BC encore présents dans commandes
        recount = db.execute(
            text("SELECT COUNT(*) FROM commandes WHERE reference_devis LIKE 'BC%'")
        ).scalar()
        print(f"[6] Recompte BC dans commandes : {recount}")
        if recount != EXPECTED_COUNT:
            print(f"[ABORT] Recompte attendu {EXPECTED_COUNT}, trouvé {recount}.")
            db.rollback()
            sys.exit(3)

        # 7. DELETE FROM commandes
        stmt_c = text(
            "DELETE FROM commandes WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        nb_supprimees = db.execute(stmt_c, {"ids": ids}).rowcount
        print(f"[7] commandes supprimées : {nb_supprimees}")

        # 8. Sanity check final
        if nb_supprimees != EXPECTED_COUNT:
            print(f"[ABORT] Attendu {EXPECTED_COUNT} suppressions, fait {nb_supprimees}.")
            db.rollback()
            sys.exit(4)

        # 9. Commit
        db.commit()
        print()
        print("[OK] Cleanup terminé")
        print(f"  commandes supprimées       : {nb_supprimees}")
        print(f"  prestations déliées        : {nb_prestations}")
        print(f"  commande_lignes supprimées : {nb_lignes}")
        print(f"  IDs dans                   : {IDS_FILE}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
