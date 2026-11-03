"""Shared bounded login/upload counters."""
from alembic import op
import sqlalchemy as sa
revision="0008"
down_revision="0007"
branch_labels=None
depends_on=None
def upgrade():
    op.create_table("betriebs_limit",
        sa.Column("schluessel",sa.String(64),primary_key=True),
        sa.Column("anzahl",sa.Integer(),nullable=False),
        sa.Column("bis",sa.DateTime(timezone=True),nullable=False))
def downgrade():op.drop_table("betriebs_limit")
