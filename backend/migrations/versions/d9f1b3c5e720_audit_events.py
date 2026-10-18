# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""audit events: who did what, for actions that don't change a row of their own
(an admin viewing the dashboard as an instructor)

Revision ID: d9f1b3c5e720
Revises: c8e0a2b4d619
Create Date: 2026-10-18 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9f1b3c5e720'
down_revision: Union[str, Sequence[str], None] = 'c8e0a2b4d619'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'audit_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor', sa.String(length=120), nullable=False),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('target', sa.String(length=200), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_events')),
    )
    op.create_index(op.f('ix_audit_events_at'), 'audit_events', ['at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_audit_events_at'), table_name='audit_events')
    op.drop_table('audit_events')
