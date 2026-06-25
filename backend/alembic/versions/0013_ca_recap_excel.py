"""ca_recap_excel : import des onglets 'recapitulatif' des Excel marge brute (2015->2026)

Stocke le recapitulatif TEL QUEL : une ligne = une famille pour une annee
(familles x 12 mois + total), sans recalcul metier.

Cle metier = (annee, ordre) : on garde l'ORDRE des lignes du recap, car un meme
code_compte peut apparaitre sur 2 familles distinctes la meme annee (ex. 70701900 =
marchandises ET logiciels en 2025) -> ne jamais regrouper sur le code seul.

Idempotence : le boot fait un create_all() qui peut creer la table AVANT cette
migration (cf. note "create_all vs Alembic"). create_table garde par get_table_names().
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

TABLE = "ca_recap_excel"


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if TABLE not in insp.get_table_names():
        cols = [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("annee", sa.Integer(), nullable=False),
            sa.Column("ordre", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("code_compte", sa.String(length=20), nullable=True),
            sa.Column("famille_libelle", sa.String(length=255), nullable=False),
        ]
        cols += [sa.Column(f"m{m:02d}", sa.Numeric(14, 2), nullable=True) for m in range(1, 13)]
        cols.append(sa.Column("total_ht", sa.Numeric(14, 2), nullable=False, server_default="0"))
        op.create_table(TABLE, *cols)
        op.create_index(f"ix_{TABLE}_annee", TABLE, ["annee"])
        op.create_index(f"ix_{TABLE}_annee_ordre", TABLE, ["annee", "ordre"])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if TABLE in insp.get_table_names():
        op.drop_table(TABLE)
