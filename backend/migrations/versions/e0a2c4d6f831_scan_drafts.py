# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""scan drafts: manual scans wait for an admin's review before they count

Revision ID: e0a2c4d6f831
Revises: d9f1b3c5e720
Create Date: 2026-10-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e0a2c4d6f831'
down_revision: Union[str, Sequence[str], None] = 'd9f1b3c5e720'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('scan_runs') as batch:
        batch.add_column(sa.Column('reviewed_by', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('review_decision', sa.String(length=16), nullable=True))
    op.create_table(
        'scan_drafts',
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('contest_slug', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('contest', sa.JSON(), nullable=False),
        sa.Column('rows', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['scan_runs.id'], name=op.f('fk_scan_drafts_run_id_scan_runs'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('run_id', name=op.f('pk_scan_drafts')),
    )
    op.create_index(op.f('ix_scan_drafts_contest_slug'), 'scan_drafts', ['contest_slug'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_scan_drafts_contest_slug'), table_name='scan_drafts')
    op.drop_table('scan_drafts')
    with op.batch_alter_table('scan_runs') as batch:
        batch.drop_column('review_decision')
        batch.drop_column('reviewed_at')
        batch.drop_column('reviewed_by')
