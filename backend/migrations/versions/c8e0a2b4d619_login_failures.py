# Author: Rajveer Sharma
# © NxtWave
# Date: 16 October 2026
"""login failures: the sign-in throttle, shared by every API process

Revision ID: c8e0a2b4d619
Revises: b3d5f7a9c104
Create Date: 2026-10-16 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8e0a2b4d619'
down_revision: Union[str, Sequence[str], None] = 'b3d5f7a9c104'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'login_failures',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=200), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_login_failures')),
    )
    op.create_index(op.f('ix_login_failures_key'), 'login_failures', ['key'], unique=False)
    op.create_index(op.f('ix_login_failures_at'), 'login_failures', ['at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_login_failures_at'), table_name='login_failures')
    op.drop_index(op.f('ix_login_failures_key'), table_name='login_failures')
    op.drop_table('login_failures')
