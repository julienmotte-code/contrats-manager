"""drop lots_facturation + fix indices_revision uniqueness

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-21

Migration 0002 - Vague 1 chantier 1.4

Changements :
1. Drop de la table lots_facturation (vide en prod, code retiré au chantier 1.2)
2. Drop de la contrainte UNIQUE sur indices_revision.date_publication
3. Création de la contrainte UNIQUE sur indices_revision (annee, mois)
   conforme à CODING_RULES.md § 9 (Août et Octobre même année possibles)

Migration manuelle car autogenerate produit 32 opérations parasites
(server_default, Index, comment manquants dans models.py).
Voir backend/alembic/README.md section "Migrations manuelles".

Note sur le downgrade — la table lots_facturation est recréée selon
l'état RÉEL constaté en DB de prod (cf. \\d lots_facturation), pas
selon les `default=` Python du modèle SQLAlchemy original. Les
`default=` Python n'avaient JAMAIS créé de server_default SQL ;
seul `server_default=func.now()` sur `declenche_at` était matérialisé
côté DB.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop de la table lots_facturation
    op.drop_table('lots_facturation')

    # 2. Drop de l'ancienne contrainte UNIQUE sur date_publication
    op.drop_constraint(
        'indices_revision_date_publication_key',
        'indices_revision',
        type_='unique'
    )

    # 3. Création de la nouvelle contrainte UNIQUE sur (annee, mois)
    op.create_unique_constraint(
        'uq_indices_revision_annee_mois',
        'indices_revision',
        ['annee', 'mois']
    )


def downgrade() -> None:
    # Inverse strict de upgrade() pour permettre un rollback

    # 3. Drop de la contrainte (annee, mois)
    op.drop_constraint(
        'uq_indices_revision_annee_mois',
        'indices_revision',
        type_='unique'
    )

    # 2. Recréation de l'ancienne contrainte UNIQUE sur date_publication
    op.create_unique_constraint(
        'indices_revision_date_publication_key',
        'indices_revision',
        ['date_publication']
    )

    # 1. Recréation de la table lots_facturation
    # Définition reconstruite à partir du modèle SQLAlchemy retiré au
    # chantier 1.2 (commit 870e8b7) ET de l'état DB réel constaté en
    # prod (psql \\d lots_facturation). Seul declenche_at portait un
    # server_default — les autres `default=...` du modèle étaient
    # Python-side et n'avaient pas été matérialisés en DB.
    op.create_table(
        'lots_facturation',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('annee_traitement', sa.Integer(), nullable=False),
        sa.Column('indice_utilise_id', sa.UUID(), nullable=True),
        sa.Column('declenche_par', sa.String(length=100), nullable=True),
        sa.Column('declenche_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('nb_contrats_traites', sa.Integer(), nullable=True),
        sa.Column('nb_factures_emises', sa.Integer(), nullable=True),
        sa.Column('nb_erreurs', sa.Integer(), nullable=True),
        sa.Column('statut', sa.String(length=20), nullable=True),
        sa.Column('termine_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rapport_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ['indice_utilise_id'],
            ['indices_revision.id'],
            name='lots_facturation_indice_utilise_id_fkey',
        ),
        sa.PrimaryKeyConstraint('id', name='lots_facturation_pkey'),
    )
