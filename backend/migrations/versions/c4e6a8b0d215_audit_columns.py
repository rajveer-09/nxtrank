# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""audit columns: who changed students / logins, when, and how (ui, excel, ...)

Revision ID: c4e6a8b0d215
Revises: b2d4f6a8c913
Create Date: 2026-10-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e6a8b0d215'
down_revision: Union[str, Sequence[str], None] = 'b2d4f6a8c913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('students', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('created_via', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('updated_by', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('updated_via', sa.String(length=10), nullable=True))
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('created_via', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('updated_by', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('updated_via', sa.String(length=10), nullable=True))
    # students so far came from the Google Sheet sync
    op.execute("UPDATE students SET created_via = 'sheet', updated_via = 'sheet'")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        for col in ('updated_via', 'updated_by', 'updated_at', 'created_via', 'created_by'):
            batch_op.drop_column(col)
    with op.batch_alter_table('students', schema=None) as batch_op:
        for col in ('updated_via', 'updated_by', 'created_via', 'created_by'):
            batch_op.drop_column(col)
