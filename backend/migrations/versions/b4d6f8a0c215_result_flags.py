# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""result flags: students LeetCode removed or moved to the bottom after a contest

Revision ID: b4d6f8a0c215
Revises: a3c5e7f9b104
Create Date: 2026-10-18 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4d6f8a0c215'
down_revision: Union[str, Sequence[str], None] = 'a3c5e7f9b104'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('results') as batch:
        batch.add_column(sa.Column('flag', sa.String(length=20), nullable=True))
        batch.add_column(sa.Column('early_rank', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('early_score', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('early_solved', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('results') as batch:
        batch.drop_column('early_solved')
        batch.drop_column('early_score')
        batch.drop_column('early_rank')
        batch.drop_column('flag')
