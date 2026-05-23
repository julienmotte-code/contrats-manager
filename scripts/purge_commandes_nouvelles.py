"""
Purge des commandes au statut 'nouvelle' — one-shot, à exécuter UNE seule fois
avant la bascule de la source de synchronisation devis → bons de commande Karlia.

Contexte
========
Jusqu'à présent, la table `commandes` était alimentée par les DEVIS Karlia
(type=1). À partir de cette refonte, elle sera alimentée par les BONS DE
COMMANDE (type=2). Comme la chaîne de résolution (BC → opportunité → client)
et l'identifiant Karlia (karlia_document_id) ne sont plus les mêmes, les
anciennes commandes au statut 'nouvelle' (jamais validées par un gestionnaire)
deviennent obsolètes : elles seraient ré-importées en double sous leur forme BC.

Ce script :
1. Crée un backup SQL (INSERTs) des commandes 'nouvelle' + leurs lignes dans
   backups/backup_pre_purge_nouvelles_<timestamp>.sql. Tente d'abord pg_dump,
   sinon export SQL manuel via SQLAlchemy (compatible exécution en conteneur
   où pg_dump n'est pas toujours installé).
2. Vérifie qu'aucune prestation n'est rattachée à une commande 'nouvelle'.
   En cas de prestation orpheline détectée : AVORTE et logue les IDs.
3. Supprime les commande_lignes des commandes 'nouvelle', puis les commandes
   'nouvelle' elles-mêmes (ordre FK respecté).
4. Réinitialise le paramètre 'derniere_synchro_devis' à NULL pour forcer un
   premier run complet de la prochaine sync (qui rapatriera les BC).

Garde-fous :
- Confirmation interactive obligatoire (tape "OUI") avant tout DELETE.
- Les commandes aux statuts AVANCÉS (a_planifier, planifiee, deployee,
  facturee, terminee) sont CONSERVÉES sans condition.
- Transaction unique, rollback automatique si une étape échoue.

Usage
=====
    docker compose exec backend python -m scripts.purge_commandes_nouvelles

Ou directement :
    python scripts/purge_commandes_nouvelles.py
"""
import os
import sys
import shutil
import subprocess
from datetime import datetime
from decimal import Decimal

# Permet l'exécution depuis la racine du projet : `python scripts/purge_commandes_nouvelles.py`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import text  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.config import settings  # noqa: E402


STATUT_PURGE = "nouvelle"
STATUTS_AVANCES = ("a_planifier", "planifiee", "deployee", "facturee", "terminee")
BACKUPS_DIR = os.path.join(os.path.dirname(__file__), "..", "backups")


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_backups_dir() -> None:
    os.makedirs(BACKUPS_DIR, exist_ok=True)


def _backup_via_pg_dump(backup_path: str) -> bool:
    """Tente un pg_dump des tables commandes + commande_lignes. Renvoie True si OK."""
    pg_dump = shutil.which("pg_dump")
    if not pg_dump:
        print("[backup] pg_dump introuvable dans le PATH — fallback SQL manuel.")
        return False

    # postgresql://user:pass@host:port/dbname
    url = settings.DATABASE_URL
    try:
        cmd = [
            pg_dump,
            "--dbname", url,
            "--data-only",
            "--column-inserts",
            "--table", "commandes",
            "--table", "commande_lignes",
            "--file", backup_path,
        ]
        print(f"[backup] pg_dump → {backup_path}")
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[backup] pg_dump a échoué ({e}) — fallback SQL manuel.")
        return False


def _sql_literal(value) -> str:
    """Représentation SQL Postgres minimaliste pour un INSERT statique."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat(sep=' ')}'"
    # str, date, UUID, etc.
    return "'" + str(value).replace("'", "''") + "'"


def _backup_via_sqlalchemy(db, backup_path: str, commande_ids: list) -> None:
    """Export SQL des commandes 'nouvelle' + leurs lignes au format INSERT."""
    print(f"[backup] export SQL manuel via SQLAlchemy → {backup_path}")
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(f"-- Backup pré-purge commandes statut='{STATUT_PURGE}'\n")
        f.write(f"-- Généré le {datetime.now().isoformat()}\n")
        f.write(f"-- Commandes : {len(commande_ids)}\n\n")
        f.write("BEGIN;\n\n")

        if not commande_ids:
            f.write("-- Aucune commande à sauvegarder\n")
            f.write("COMMIT;\n")
            return

        # Récupérer les commandes
        cmd_rows = db.execute(
            text("SELECT * FROM commandes WHERE id = ANY(:ids) ORDER BY id"),
            {"ids": commande_ids},
        ).mappings().all()
        if cmd_rows:
            cols = list(cmd_rows[0].keys())
            f.write(f"-- commandes ({len(cmd_rows)} lignes)\n")
            for row in cmd_rows:
                values = ", ".join(_sql_literal(row[c]) for c in cols)
                f.write(
                    f"INSERT INTO commandes ({', '.join(cols)}) VALUES ({values});\n"
                )
            f.write("\n")

        # Récupérer les lignes
        ligne_rows = db.execute(
            text("SELECT * FROM commande_lignes WHERE commande_id = ANY(:ids) ORDER BY id"),
            {"ids": commande_ids},
        ).mappings().all()
        if ligne_rows:
            cols = list(ligne_rows[0].keys())
            f.write(f"-- commande_lignes ({len(ligne_rows)} lignes)\n")
            for row in ligne_rows:
                values = ", ".join(_sql_literal(row[c]) for c in cols)
                f.write(
                    f"INSERT INTO commande_lignes ({', '.join(cols)}) VALUES ({values});\n"
                )
            f.write("\n")

        f.write("COMMIT;\n")


def _count_by_statut(db, statut: str) -> int:
    return db.execute(
        text("SELECT COUNT(*) FROM commandes WHERE statut = :s"), {"s": statut}
    ).scalar() or 0


def _count_avances(db) -> int:
    return db.execute(
        text("SELECT COUNT(*) FROM commandes WHERE statut = ANY(:s)"),
        {"s": list(STATUTS_AVANCES)},
    ).scalar() or 0


def _prestations_liees(db, commande_ids: list) -> list:
    if not commande_ids:
        return []
    return [
        row[0]
        for row in db.execute(
            text("SELECT id FROM prestations WHERE commande_id = ANY(:ids) ORDER BY id"),
            {"ids": commande_ids},
        ).all()
    ]


def main():
    _ensure_backups_dir()
    db = SessionLocal()
    try:
        # 1. Compter
        nb_a_purger = _count_by_statut(db, STATUT_PURGE)
        nb_avances = _count_avances(db)
        print(f"[1] Commandes statut='{STATUT_PURGE}' à supprimer : {nb_a_purger}")
        print(f"[1] Commandes aux statuts avancés (CONSERVÉES)    : {nb_avances}")

        if nb_a_purger == 0:
            print("[OK] Rien à purger. Réinitialisation derniere_synchro_devis quand même.")
            db.execute(text("DELETE FROM parametres WHERE cle = 'derniere_synchro_devis'"))
            db.commit()
            print("[OK] Paramètre 'derniere_synchro_devis' supprimé.")
            return

        # 2. Récupérer les IDs des commandes à purger
        commande_ids = [
            row[0]
            for row in db.execute(
                text("SELECT id FROM commandes WHERE statut = :s ORDER BY id"),
                {"s": STATUT_PURGE},
            ).all()
        ]
        if len(commande_ids) != nb_a_purger:
            print(f"[ABORT] Incohérence : {len(commande_ids)} IDs vs {nb_a_purger} compte.")
            sys.exit(2)

        # 3. Vérifier qu'aucune prestation n'est liée à ces commandes
        prest_ids = _prestations_liees(db, commande_ids)
        if prest_ids:
            print(
                f"[ALERTE] {len(prest_ids)} prestation(s) liée(s) à des commandes "
                f"'{STATUT_PURGE}' détectée(s) : {prest_ids[:20]}{'...' if len(prest_ids) > 20 else ''}"
            )
            print("[ABORT] Refus de supprimer : des prestations seraient orphelines.")
            print("        → Investiguer manuellement avant de relancer le script.")
            sys.exit(3)
        print(f"[2] Aucune prestation liée — OK pour suppression.")

        # 4. Backup
        backup_path = os.path.abspath(
            os.path.join(BACKUPS_DIR, f"backup_pre_purge_nouvelles_{_timestamp()}.sql")
        )
        if not _backup_via_pg_dump(backup_path):
            _backup_via_sqlalchemy(db, backup_path, commande_ids)
        print(f"[3] Backup créé : {backup_path}")

        # 5. Confirmation interactive
        print()
        print("=" * 70)
        print(f"  Tu vas SUPPRIMER {nb_a_purger} commandes (statut='{STATUT_PURGE}')")
        print(f"  + leurs lignes (commande_lignes).")
        print(f"  Backup déjà créé : {backup_path}")
        print(f"  Les {nb_avances} commandes aux statuts avancés sont CONSERVÉES.")
        print("=" * 70)
        reponse = input("Tape OUI pour confirmer : ").strip()
        if reponse != "OUI":
            print("[ABORT] Confirmation refusée. Aucune modification.")
            db.rollback()
            return

        # 6. Suppression (ordre FK : lignes puis commandes)
        nb_lignes = db.execute(
            text("DELETE FROM commande_lignes WHERE commande_id = ANY(:ids)"),
            {"ids": commande_ids},
        ).rowcount
        print(f"[4] commande_lignes supprimées : {nb_lignes}")

        nb_supprimees = db.execute(
            text("DELETE FROM commandes WHERE id = ANY(:ids)"),
            {"ids": commande_ids},
        ).rowcount
        print(f"[5] commandes supprimées : {nb_supprimees}")

        if nb_supprimees != nb_a_purger:
            print(f"[ABORT] Attendu {nb_a_purger} suppressions, fait {nb_supprimees}.")
            db.rollback()
            sys.exit(4)

        # 7. Réinitialiser la dernière synchro (forcer un full run)
        nb_param = db.execute(
            text("DELETE FROM parametres WHERE cle = 'derniere_synchro_devis'")
        ).rowcount
        print(f"[6] Paramètre 'derniere_synchro_devis' réinitialisé (rows={nb_param}).")

        # 8. Commit final
        db.commit()
        print()
        print("[OK] Purge terminée avec succès.")
        print(f"     commandes supprimées       : {nb_supprimees}")
        print(f"     commande_lignes supprimées : {nb_lignes}")
        print(f"     backup                     : {backup_path}")
        print(f"     derniere_synchro_devis     : réinitialisée")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
