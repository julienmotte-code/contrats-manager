"""miroir des ventes Karlia pour le calcul du CA

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'karlia_ca_factures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('karlia_document_id', sa.String(), nullable=False),
        sa.Column('numero', sa.String(), nullable=True),
        sa.Column('numero_int', sa.Integer(), nullable=True),
        sa.Column('date_facture', sa.Date(), nullable=False),
        sa.Column('exercice', sa.Integer(), nullable=False),
        sa.Column('montant_ht', sa.Numeric(15, 2), nullable=False),
        sa.Column('montant_ttc', sa.Numeric(15, 2), nullable=True),
        sa.Column('canceled', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('client_nom', sa.String(), nullable=True),
        sa.Column('id_opportunity', sa.String(), nullable=True),
        sa.Column('refreshed_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('karlia_document_id', name='uq_karlia_ca_factures_docid'),
    )
    op.create_index('ix_karlia_ca_factures_date_facture', 'karlia_ca_factures', ['date_facture'])
    op.create_index('ix_karlia_ca_factures_exercice', 'karlia_ca_factures', ['exercice'])
    op.create_index('ix_karlia_ca_factures_numero_int', 'karlia_ca_factures', ['numero_int'])
    op.create_index('ix_karlia_ca_factures_karlia_document_id', 'karlia_ca_factures', ['karlia_document_id'], unique=True)


def downgrade():
    op.drop_index('ix_karlia_ca_factures_karlia_document_id', table_name='karlia_ca_factures')
    op.drop_index('ix_karlia_ca_factures_numero_int', table_name='karlia_ca_factures')
    op.drop_index('ix_karlia_ca_factures_exercice', table_name='karlia_ca_factures')
    op.drop_index('ix_karlia_ca_factures_date_facture', table_name='karlia_ca_factures')
    op.drop_table('karlia_ca_factures')
