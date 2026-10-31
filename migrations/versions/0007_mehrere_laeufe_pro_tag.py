"""Mehrere Läufe pro Strecke und Tag: eine Klasse nach der anderen

An einer mehrzügigen Schule finden pro Tag zwei Übungsläufe mit verschiedenen
Klassen auf derselben Strecke statt. Der bisherige Index ließ nur einen zu.
Doppelt verhindert wird jetzt nur noch derselbe Lauf: Klasse, Strecke, Tag.

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

AKTIV = sa.text("status IN ('vorbereitet', 'laufend')")


def upgrade() -> None:
    op.drop_index('uq_lauf_strecke_datum_aktiv', table_name='lauf', postgresql_where=AKTIV)
    op.create_index(
        'uq_lauf_strecke_gruppe_datum_aktiv', 'lauf', ['strecke_id', 'gruppe_id', 'datum'],
        unique=True, postgresql_where=AKTIV,
    )


def downgrade() -> None:
    # Zurück geht es nur, solange keine Strecke an einem Tag zwei aktive Läufe hat.
    op.drop_index('uq_lauf_strecke_gruppe_datum_aktiv', table_name='lauf', postgresql_where=AKTIV)
    op.create_index(
        'uq_lauf_strecke_datum_aktiv', 'lauf', ['strecke_id', 'datum'],
        unique=True, postgresql_where=AKTIV,
    )
