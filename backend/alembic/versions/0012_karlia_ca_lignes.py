"""karlia_ca_lignes : miroir niveau ligne pour CA & marge par type de prestation

Greffe sur le socle CA existant (0010 karlia_ca_factures, qui n'agrege qu'au niveau
facture). Cette table porte le detail LIGNE (categorie d'article + cout) necessaire au
calcul de la marge par type de prestation.

Idempotence : le boot fait un create_all() qui peut creer la table AVANT cette
migration (cf. note "create_all vs Alembic"). On garde donc l'upgrade idempotent
(create_table seulement si absente) pour eviter un DuplicateTable.
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

TABLE = "karlia_ca_lignes"


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if TABLE not in insp.get_table_names():
        op.create_table(
            TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("source", sa.String(), nullable=False, server_default="karlia"),
            sa.Column("karlia_document_id", sa.String(), nullable=True),
            sa.Column("numero", sa.String(), nullable=True),
            sa.Column("numero_int", sa.Integer(), nullable=True),
            sa.Column("date_facture", sa.Date(), nullable=True),
            sa.Column("exercice", sa.Integer(), nullable=True),
            sa.Column("canceled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("id_product", sa.String(), nullable=True),
            sa.Column("categorie_id", sa.Integer(), nullable=True),
            sa.Column("categorie_nom", sa.String(), nullable=True),
            sa.Column("chart_of_account_code", sa.String(), nullable=True),
            sa.Column("chart_of_account_label", sa.String(), nullable=True),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("quantity", sa.Numeric(15, 4), nullable=True),
            sa.Column("montant_ht", sa.Numeric(15, 2), nullable=False, server_default="0"),
            sa.Column("cout", sa.Numeric(15, 2), nullable=True),
            sa.Column("cout_source", sa.String(), nullable=True),
            sa.Column("cout_disponible", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("refreshed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index(f"ix_{TABLE}_source", TABLE, ["source"])
        op.create_index(f"ix_{TABLE}_karlia_document_id", TABLE, ["karlia_document_id"])
        op.create_index(f"ix_{TABLE}_numero_int", TABLE, ["numero_int"])
        op.create_index(f"ix_{TABLE}_exercice", TABLE, ["exercice"])
        op.create_index(f"ix_{TABLE}_categorie_id", TABLE, ["categorie_id"])
        op.create_index(f"ix_{TABLE}_exercice_categorie", TABLE, ["exercice", "categorie_id"])

    # Intervalle de rafraichissement du miroir lignes (idempotent, calque sur
    # ca_refresh_interval_heures). Defaut 24 h : le fetch detail est couteux (N+1).
    op.execute(
        """
        INSERT INTO parametres (cle, valeur, description)
        SELECT 'ca_lignes_refresh_interval_heures', '24',
               'Intervalle (heures) de rafraichissement du miroir lignes CA/marge Karlia'
        WHERE NOT EXISTS (
            SELECT 1 FROM parametres WHERE cle = 'ca_lignes_refresh_interval_heures'
        )
        """
    )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if TABLE in insp.get_table_names():
        op.drop_table(TABLE)
    op.execute("DELETE FROM parametres WHERE cle = 'ca_lignes_refresh_interval_heures'")
