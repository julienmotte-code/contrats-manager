"""ajout table factures_historiques (import CA historique)

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'factures_historiques',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('numero_facture', sa.Integer(), nullable=False),
        sa.Column('date_facture', sa.Date(), nullable=False),
        sa.Column('exercice', sa.Integer(), nullable=False),
        sa.Column('client_nom', sa.String(), nullable=False),
        sa.Column('adresse', sa.String(), nullable=True),
        sa.Column('code_postal', sa.String(length=5), nullable=True),
        sa.Column('ville', sa.String(), nullable=True),
        sa.Column('montant_ht', sa.Numeric(15, 2), nullable=False),
        sa.Column('montant_tva', sa.Numeric(15, 2), nullable=False),
        sa.Column('montant_ttc', sa.Numeric(15, 2), nullable=False),
        sa.Column('taux_tva', sa.Numeric(5, 2), server_default='20.00', nullable=False),
        sa.Column('source', sa.String(), server_default='export_factura', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('numero_facture', name='uq_factures_historiques_numero'),
    )
    op.create_index('ix_factures_historiques_exercice', 'factures_historiques', ['exercice'])
    op.create_index('ix_factures_historiques_date_facture', 'factures_historiques', ['date_facture'])
    op.create_index('ix_factures_historiques_numero_facture', 'factures_historiques', ['numero_facture'], unique=True)


def downgrade():
    op.drop_index('ix_factures_historiques_numero_facture', table_name='factures_historiques')
    op.drop_index('ix_factures_historiques_date_facture', table_name='factures_historiques')
    op.drop_index('ix_factures_historiques_exercice', table_name='factures_historiques')
    op.drop_table('factures_historiques')
