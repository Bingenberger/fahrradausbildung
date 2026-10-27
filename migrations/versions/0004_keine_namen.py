"""Keine Kindernamen: Kinder sind nur noch Startnummern

Die Zuordnung Startnummer → Name führt die Klassenleitung auf Papier.
Achtung: Das Upgrade löscht vorhandene Namen endgültig.

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("kind", "vorname")
    op.drop_column("kind", "nachname")


def downgrade() -> None:
    # Die Namen lassen sich nicht wiederherstellen; die Spalten kommen leer zurück.
    op.add_column("kind", sa.Column("vorname", sa.String(100), nullable=False, server_default=""))
    op.add_column("kind", sa.Column("nachname", sa.String(100), nullable=False, server_default=""))
