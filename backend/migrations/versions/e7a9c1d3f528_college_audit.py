# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""audit columns on colleges (now managed by the super admin)

Revision ID: e7a9c1d3f528
Revises: d6f8b0c2e417
Create Date: 2026-10-15 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a9c1d3f528'
down_revision: Union[str, Sequence[str], None] = 'd6f8b0c2e417'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('colleges', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('created_by', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('created_via', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('updated_by', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('updated_via', sa.String(length=10), nullable=True))
    # colleges so far came in with the Google Sheet roster
    op.execute("UPDATE colleges SET created_via = 'sheet'")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('colleges', schema=None) as batch_op:
        for col in ('updated_via', 'updated_by', 'updated_at', 'created_via', 'created_by', 'created_at'):
            batch_op.drop_column(col)
