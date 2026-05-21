"""
Alembic environment — Module Gestion Contrats.

Particularités :
- DATABASE_URL est lue depuis l'environnement (et NON depuis alembic.ini)
  pour que les credentials ne soient pas versionnés.
- target_metadata pointe vers Base.metadata du module backend,
  ce qui permet l'autogenerate sur toutes les tables déclarées dans
  app/models/models.py.
- compare_type=True et compare_server_default=True : autogenerate
  détecte aussi les changements de type SQL et de défauts côté DB
  (et non seulement l'ajout/suppression de colonnes).
- Pas de support du mode offline (`alembic upgrade --sql`) : on
  exécute toujours les migrations contre une DB live.
"""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Cette ligne donne accès à la config Alembic (depuis alembic.ini)
config = context.config

# Configuration des logs depuis alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── Injection de DATABASE_URL ────────────────────────────────────
database_url = os.environ.get("DATABASE_URL")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL n'est pas définie dans l'environnement. "
        "Alembic ne peut pas se connecter à la base. "
        "Vérifier docker-compose.yml ou les variables d'environnement."
    )
config.set_main_option("sqlalchemy.url", database_url)

# ── Métadonnées cibles pour autogenerate ─────────────────────────
# L'import doit charger tous les modèles SQLAlchemy ; Base.metadata
# en collecte la liste exhaustive.
from app.models.models import Base  # noqa: E402  (import après config)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    """Lance les migrations en mode online (connexion active à la DB).

    Création d'un Engine éphémère, ouverture d'une connexion, association
    au contexte Alembic et exécution des migrations dans une transaction.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,             # autogenerate détecte les changements de type SQL
            compare_server_default=True,   # autogenerate détecte les changements de DEFAULT
        )

        with context.begin_transaction():
            context.run_migrations()


# Mode offline non supporté pour ce projet (cf. docstring du module).
if context.is_offline_mode():
    raise RuntimeError(
        "Mode offline non supporté par ce projet. "
        "Utiliser 'alembic upgrade head' sans --sql, ou consulter alembic/README.md."
    )

run_migrations_online()
