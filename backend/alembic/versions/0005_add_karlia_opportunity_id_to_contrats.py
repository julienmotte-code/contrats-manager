"""add karlia_opportunity_id to contrats

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-27

Ajoute la colonne karlia_opportunity_id (nullable) sur contrats pour
rattacher la facture annuelle Syntec à l'opportunité Karlia d'origine
quand le contrat provient d'une commande (nouveau client). Reste NULL
pour les renouvellements (pas d'opportunité).
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'contrats',
        sa.Column('karlia_opportunity_id', sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column('contrats', 'karlia_opportunity_id')
