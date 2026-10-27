"""Karte: Verlauf der Strecke und Standort der Posten

Revision ID: 0005
Revises: 0004
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, Sequence[str], None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("strecke", sa.Column("verlauf", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("posten", sa.Column("lat", sa.Double(), nullable=True))
    op.add_column("posten", sa.Column("lng", sa.Double(), nullable=True))
    # Name "ort" – die Namenskonvention macht daraus ck_posten_ort.
    op.create_check_constraint(
        "ort",
        "posten",
        "(lat IS NULL) = (lng IS NULL) AND (lat IS NULL OR (lat BETWEEN -90 AND 90 AND lng BETWEEN -180 AND 180))",
    )


def downgrade() -> None:
    op.drop_constraint("ort", "posten", type_="check")
    op.drop_column("posten", "lng")
    op.drop_column("posten", "lat")
    op.drop_column("strecke", "verlauf")
