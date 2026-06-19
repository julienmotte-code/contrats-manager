"""add prorate_demi_mois_moins to contrats"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("contrats", sa.Column(
        "prorate_demi_mois_moins", sa.Boolean(),
        nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("contrats", "prorate_demi_mois_moins")
