"""Aufbewahrung: Zeitpunkt der Löschung der Erfassungen eines Laufs

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("lauf", sa.Column("daten_geloescht_am", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("lauf", "daten_geloescht_am")
