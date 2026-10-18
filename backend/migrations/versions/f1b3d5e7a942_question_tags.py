# Author: Rajveer Sharma
# © NxtWave
# Date: 18 October 2026
"""question tags: raw tags per source (official / community), each question's state,
and the effective tags the topic stats use

Revision ID: f1b3d5e7a942
Revises: e0a2c4d6f831
Create Date: 2026-10-18 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1b3d5e7a942'
down_revision: Union[str, Sequence[str], None] = 'e0a2c4d6f831'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'question_tag_sources',
        sa.Column('question_slug', sa.String(length=200), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.Column('tag_slug', sa.String(length=100), nullable=False),
        sa.Column('tag_name', sa.String(length=100), nullable=False),
        sa.Column('mentions', sa.Integer(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('question_slug', 'source', 'tag_slug', name=op.f('pk_question_tag_sources')),
    )
    op.create_table(
        'question_tag_status',
        sa.Column('question_slug', sa.String(length=200), nullable=False),
        sa.Column('official_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('official_found', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('community_fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('community_mentions', sa.Integer(), nullable=True),
        sa.Column('state', sa.String(length=12), nullable=False),
        sa.Column('effective_hash', sa.String(length=40), nullable=True),
        sa.Column('state_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('question_slug', name=op.f('pk_question_tag_status')),
    )
    op.create_table(
        'question_tags',
        sa.Column('question_slug', sa.String(length=200), nullable=False),
        sa.Column('tag_slug', sa.String(length=100), nullable=False),
        sa.Column('tag_name', sa.String(length=100), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.PrimaryKeyConstraint('question_slug', 'tag_slug', name=op.f('pk_question_tags')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('question_tags')
    op.drop_table('question_tag_status')
    op.drop_table('question_tag_sources')
