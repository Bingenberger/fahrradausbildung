"""Abläufe: wiederkehrende Handlungsabläufe als Vorlage für Posten

Revision ID: 0006
Revises: 0005
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('ablauf',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('schule_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('beschreibung', sa.Text(), server_default='', nullable=False),
    sa.ForeignKeyConstraint(['schule_id'], ['schule.id'], name=op.f('fk_ablauf_schule_id_schule'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ablauf'))
    )
    op.create_index(op.f('ix_ablauf_schule_id'), 'ablauf', ['schule_id'], unique=False)
    op.create_table('ablauf_schritt',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('ablauf_id', sa.Integer(), nullable=False),
    sa.Column('kurzbezeichnung', sa.String(length=60), nullable=False),
    sa.Column('beobachtungstext', sa.Text(), server_default='', nullable=False),
    sa.Column('uebungstext', sa.Text(), server_default='', nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['ablauf_id'], ['ablauf.id'], name=op.f('fk_ablauf_schritt_ablauf_id_ablauf'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ablauf_schritt'))
    )
    op.create_index(op.f('ix_ablauf_schritt_ablauf_id'), 'ablauf_schritt', ['ablauf_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_ablauf_schritt_ablauf_id'), table_name='ablauf_schritt')
    op.drop_table('ablauf_schritt')
    op.drop_index(op.f('ix_ablauf_schule_id'), table_name='ablauf')
    op.drop_table('ablauf')
