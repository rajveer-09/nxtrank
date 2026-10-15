# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""upload history: Excel uploads and what each changed (for undo)

Revision ID: f9b1d3e5a730
Revises: e7a9c1d3f528
Create Date: 2026-10-15 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9b1d3e5a730'
down_revision: Union[str, Sequence[str], None] = 'e7a9c1d3f528'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'uploads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('uploaded_by', sa.String(length=120), nullable=False),
        sa.Column('via', sa.String(length=10), nullable=False),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('rows', sa.Integer(), nullable=False),
        sa.Column('counts', sa.JSON(), nullable=False),
        sa.Column('issues', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=10), nullable=False),
        sa.Column('undone_by', sa.String(length=120), nullable=True),
        sa.Column('undone_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('undo_result', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_uploads')),
    )
    op.create_table(
        'upload_changes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('upload_id', sa.Integer(), nullable=False),
        sa.Column('entity', sa.String(length=16), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=300), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('before', sa.JSON(), nullable=True),
        sa.Column('after', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['upload_id'], ['uploads.id'], name=op.f('fk_upload_changes_upload_id_uploads'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_upload_changes')),
    )
    op.create_index(op.f('ix_upload_changes_upload_id'), 'upload_changes', ['upload_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_upload_changes_upload_id'), table_name='upload_changes')
    op.drop_table('upload_changes')
    op.drop_table('uploads')
