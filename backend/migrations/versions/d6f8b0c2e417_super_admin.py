# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""super admin flag; rajveer.sharma@nxtwave.co.in is the super admin

Revision ID: d6f8b0c2e417
Revises: c4e6a8b0d215
Create Date: 2026-10-15 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6f8b0c2e417'
down_revision: Union[str, Sequence[str], None] = 'c4e6a8b0d215'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SUPER_ADMIN = "rajveer.sharma@nxtwave.co.in"


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_super', sa.Boolean(), server_default=sa.false(), nullable=False))
    users = sa.table("users", sa.column("username", sa.String), sa.column("role", sa.String),
                     sa.column("is_super", sa.Boolean))
    op.execute(users.update().where(users.c.username == SUPER_ADMIN, users.c.role == "admin").values(is_super=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('is_super')
