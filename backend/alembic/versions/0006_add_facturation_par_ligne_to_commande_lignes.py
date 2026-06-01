"""add facturation par ligne to commande_lignes

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-01

Ajoute la trace de facturation AU NIVEAU LIGNE sur commande_lignes pour
permettre la facturation par sélection de lignes 'facturation_directe'
(écran "Terminées" refondu) indépendamment du statut de la commande parente :

  - facture_karlia_id  : id du document Karlia (brouillon) émis pour la ligne ;
                         NULL = ligne pas encore facturée (= éligible).
  - facture_karlia_ref : référence Karlia affichable de la facture.
  - date_facturee      : horodatage du marquage facturé.

Anti-doublon : une ligne avec facture_karlia_id NON NULL est exclue de la
liste à facturer et de toute nouvelle sélection.

SQL idempotent (IF NOT EXISTS) : sans danger si les colonnes existent déjà
(cf. précédent destination/section_karlia ajoutées hors Alembic sur cette
même table).
"""
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE commande_lignes "
        "ADD COLUMN IF NOT EXISTS facture_karlia_id VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE commande_lignes "
        "ADD COLUMN IF NOT EXISTS facture_karlia_ref VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE commande_lignes "
        "ADD COLUMN IF NOT EXISTS date_facturee TIMESTAMP"
    )


def downgrade():
    op.execute("ALTER TABLE commande_lignes DROP COLUMN IF EXISTS date_facturee")
    op.execute("ALTER TABLE commande_lignes DROP COLUMN IF EXISTS facture_karlia_ref")
    op.execute("ALTER TABLE commande_lignes DROP COLUMN IF EXISTS facture_karlia_id")
