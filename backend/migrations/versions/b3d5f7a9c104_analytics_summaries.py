# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""analytics read model: student_stats, cohort_stats, data_version

Revision ID: b3d5f7a9c104
Revises: a1c3e5f7b902
Create Date: 2026-10-16 10:00:00.000000

Precomputed analytics, rebuilt by app.services.summaries
whenever results or the roster change. data_version counts committed data changes;
API ETags are built from it.
"""
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b3d5f7a9c104'
down_revision: Union[str, Sequence[str], None] = 'a1c3e5f7b902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'student_stats',
        sa.Column('win', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('scanned', sa.Integer(), nullable=False),
        sa.Column('attended', sa.Integer(), nullable=False),
        sa.Column('sum_solved', sa.Integer(), nullable=False),
        sa.Column('sum_solved_sq', sa.Integer(), nullable=False),
        sa.Column('max_solved', sa.Integer(), nullable=True),
        sa.Column('avg_top_pct', sa.Float(), nullable=True),
        sa.Column('best_global_rank', sa.Integer(), nullable=True),
        sa.Column('best_college_rank', sa.Integer(), nullable=True),
        sa.Column('points', sa.Integer(), nullable=False),
        sa.Column('total_time', sa.BigInteger(), nullable=False),
        sa.Column('longest_streak', sa.Integer(), nullable=False),
        sa.Column('current_streak', sa.Integer(), nullable=False),
        sa.Column('absent_streak', sa.Integer(), nullable=False),
        sa.Column('trend_k', sa.Integer(), nullable=True),
        sa.Column('trend_recent', sa.Integer(), nullable=True),
        sa.Column('trend_before', sa.Integer(), nullable=True),
        sa.Column('questions', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ondelete='CASCADE',
                                name=op.f('fk_student_stats_student_id_students')),
        sa.PrimaryKeyConstraint('win', 'student_id', name=op.f('pk_student_stats')),
    )
    op.create_table(
        'cohort_stats',
        sa.Column('win', sa.Integer(), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint('win', name=op.f('pk_cohort_stats')),
    )
    app_state = sa.table('app_state', sa.column('key', sa.String), sa.column('value', sa.Text),
                         sa.column('updated_at', sa.DateTime(timezone=True)))
    # a random start: a recreated database never repeats an earlier one's versions (or ETags)
    start = str(secrets.randbits(40))
    op.execute(app_state.insert().values(key='data_version', value=start, updated_at=sa.func.current_timestamp()))


def downgrade() -> None:
    op.execute("DELETE FROM app_state WHERE key = 'data_version'")
    op.drop_table('cohort_stats')
    op.drop_table('student_stats')
