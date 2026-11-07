"""Optionale PIN vor der Posten-App, einstellbar je Schule

Revision ID: 0009
Revises: 0008
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schule", sa.Column("posten_pin", sa.String(4), nullable=True))
    op.create_check_constraint(op.f("ck_schule_posten_pin"), "schule", "posten_pin ~ '^[0-9]{4}$'")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_schule_posten_pin"), "schule", type_="check")
    op.drop_column("schule", "posten_pin")
