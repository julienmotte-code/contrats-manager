"""baseline - existing database

Revision ID: 0001
Revises:
Create Date: 2026-05-21

Cette migration est un no-op intentionnel. Elle marque le point zéro
du versioning Alembic pour une base de données préexistante.

Toutes les évolutions de schéma à partir d'ici doivent passer par
une nouvelle migration Alembic (migrations 0002, 0003, ...).

Voir backend/alembic/README.md pour le workflow.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """No-op baseline. La DB existe déjà avec son schéma complet."""
    pass


def downgrade() -> None:
    """No-op. La baseline ne peut pas être dégradée — c'est le point zéro."""
    pass
