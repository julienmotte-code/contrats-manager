"""add quantite_max_facturable on factures_fournisseurs_lignes

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-25

Migration 0004 — Snapshot du restant facturable à la création.

Ajoute une colonne `quantite_max_facturable` (Numeric(12,3), nullable) sur
`factures_fournisseurs_lignes`. Renseignée à la création / mise à jour
d'un brouillon par le backend (= livré Karlia − cumul facturé au moment T).

Objectif perf : permettre à l'écran d'édition de borner les champs `max`
des quantités SANS rappeler GET /api/factures-fournisseurs/facturables
(qui coûte ~10 s — catalogue produits + listing suppliers-documents +
détails BR).

Nullable : les lignes existantes (créées avant cette migration) gardent
NULL. Le front les traite comme « pas de borne connue » et retombe sur
la quantité actuelle (sécurité). Le backend revalide toujours côté
serveur à la validation, donc la borne front est purement ergonomique.

Migration manuelle (autogenerate désactivé — cf. backend/alembic/README.md).
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'factures_fournisseurs_lignes',
        sa.Column(
            'quantite_max_facturable',
            sa.Numeric(precision=12, scale=3),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        'factures_fournisseurs_lignes',
        'quantite_max_facturable',
    )
