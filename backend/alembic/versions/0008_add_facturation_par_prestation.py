"""add facturation par prestation to prestations

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-01

Ajoute la trace de facturation AU NIVEAU PRESTATION sur prestations, en miroir
de ce qui existe sur commande_lignes (migration 0006). Permet de facturer une
prestation réalisée vers Karlia (seule ou groupée avec des lignes
facturation_directe), indépendamment de la commande parente :

  - facture_karlia_id  : id du document Karlia (brouillon) émis ; NULL = pas
                         encore facturée (= éligible à l'écran "Terminées").
  - facture_karlia_ref : référence Karlia affichable.
  - date_facturee      : horodatage du marquage facturé.

Anti-doublon : une prestation avec facture_karlia_id NON NULL est exclue de la
liste à facturer et de toute nouvelle sélection.

Pas de backfill : aucune prestation facturable historiquement (confirmé par
diag facturation-prestations). SQL idempotent (IF NOT EXISTS).
"""
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE prestations "
        "ADD COLUMN IF NOT EXISTS facture_karlia_id VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE prestations "
        "ADD COLUMN IF NOT EXISTS facture_karlia_ref VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE prestations "
        "ADD COLUMN IF NOT EXISTS date_facturee TIMESTAMP"
    )


def downgrade():
    op.execute("ALTER TABLE prestations DROP COLUMN IF EXISTS date_facturee")
    op.execute("ALTER TABLE prestations DROP COLUMN IF EXISTS facture_karlia_ref")
    op.execute("ALTER TABLE prestations DROP COLUMN IF EXISTS facture_karlia_id")
