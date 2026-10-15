# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""profile ranks: leaderboard position kept separately, rank source

Revision ID: a7c3e91b2d40
Revises: e865ec62d274
Create Date: 2026-10-14 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c3e91b2d40'
down_revision: Union[str, Sequence[str], None] = 'e865ec62d274'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('results', schema=None) as batch_op:
        batch_op.add_column(sa.Column('leaderboard_rank', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('rank_source', sa.String(length=10), nullable=True))
    # existing rows were stored from the leaderboard position
    op.execute("UPDATE results SET leaderboard_rank = global_rank, rank_source = 'scan' WHERE global_rank IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('results', schema=None) as batch_op:
        batch_op.drop_column('rank_source')
        batch_op.drop_column('leaderboard_rank')
