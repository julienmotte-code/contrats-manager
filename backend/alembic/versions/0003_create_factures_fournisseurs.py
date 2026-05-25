"""create factures_fournisseurs tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-25

Migration 0003 - Factures fournisseurs (étape 1/3 — couche données)

Création des 3 tables nécessaires à la construction de factures
fournisseurs côté SGI à partir des bons de réception Karlia :

1. factures_fournisseurs            — en-tête (1 fournisseur par facture)
2. factures_fournisseurs_lignes     — lignes facturées (référence ligne BR source)
3. factures_fournisseurs_pointage   — anti-doublon avec cumul partiel
                                       (UNIQUE sur (id_bl_karlia, ligne_index))

Émission Karlia non implémentée à ce stade (POST /suppliers-documents
renvoie "API not available", en attente support Karlia). Les colonnes
id_suppliers_document_karlia et statut_emission_karlia sont prévues pour
brancher l'émission ultérieurement sans refonte.

Migration manuelle (autogenerate désactivé — cf. backend/alembic/README.md
section "Migrations manuelles").
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Table en-tête
    op.create_table(
        'factures_fournisseurs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('id_fournisseur_karlia', sa.Integer(), nullable=False),
        sa.Column('nom_fournisseur', sa.String(length=255), nullable=True),
        sa.Column('statut', sa.String(length=20), server_default=sa.text("'brouillon'"), nullable=False),
        sa.Column('date_facture', sa.Date(), nullable=True),
        sa.Column('reference', sa.String(length=200), nullable=True),
        sa.Column('total_ht', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
        sa.Column('total_tva', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
        sa.Column('total_ttc', sa.Numeric(precision=12, scale=2), server_default=sa.text('0'), nullable=False),
        sa.Column('id_suppliers_document_karlia', sa.Integer(), nullable=True),
        sa.Column('statut_emission_karlia', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='factures_fournisseurs_pkey'),
    )
    op.create_index(
        'ix_factures_fournisseurs_fournisseur_statut',
        'factures_fournisseurs',
        ['id_fournisseur_karlia', 'statut'],
    )

    # 2. Table lignes
    op.create_table(
        'factures_fournisseurs_lignes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('id_facture_fournisseur', sa.Integer(), nullable=False),
        sa.Column('id_bl_karlia', sa.Integer(), nullable=False),
        sa.Column('ligne_index', sa.Integer(), nullable=False),
        sa.Column('id_product_karlia', sa.Integer(), nullable=True),
        sa.Column('designation', sa.String(length=500), nullable=False),
        sa.Column('reference', sa.String(length=200), nullable=True),
        sa.Column('quantite', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('prix_unitaire_ht', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('id_vat_karlia', sa.String(length=10), nullable=True),
        sa.Column('total_ht', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(
            ['id_facture_fournisseur'],
            ['factures_fournisseurs.id'],
            name='factures_fournisseurs_lignes_id_facture_fournisseur_fkey',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id', name='factures_fournisseurs_lignes_pkey'),
    )
    op.create_index(
        'ix_factures_fournisseurs_lignes_bl_ligne',
        'factures_fournisseurs_lignes',
        ['id_bl_karlia', 'ligne_index'],
    )

    # 3. Table pointage (anti-doublon, cumul partiel)
    op.create_table(
        'factures_fournisseurs_pointage',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('id_bl_karlia', sa.Integer(), nullable=False),
        sa.Column('ligne_index', sa.Integer(), nullable=False),
        sa.Column('quantite_livree', sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column('quantite_facturee_cumulee', sa.Numeric(precision=12, scale=3), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='factures_fournisseurs_pointage_pkey'),
        sa.UniqueConstraint(
            'id_bl_karlia',
            'ligne_index',
            name='uq_factures_fournisseurs_pointage_bl_ligne',
        ),
    )


def downgrade() -> None:
    # Inverse strict de upgrade() pour permettre un rollback.
    # Ordre : tables dépendantes d'abord (lignes -> en-tête), puis pointage.
    op.drop_table('factures_fournisseurs_pointage')

    op.drop_index(
        'ix_factures_fournisseurs_lignes_bl_ligne',
        table_name='factures_fournisseurs_lignes',
    )
    op.drop_table('factures_fournisseurs_lignes')

    op.drop_index(
        'ix_factures_fournisseurs_fournisseur_statut',
        table_name='factures_fournisseurs',
    )
    op.drop_table('factures_fournisseurs')
