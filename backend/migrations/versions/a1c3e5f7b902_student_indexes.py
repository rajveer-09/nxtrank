# Author: Rajveer Sharma
# © NxtWave
# Date: 15 October 2026
"""indexes for "everything about one student" (results, problem_results)

Revision ID: a1c3e5f7b902
Revises: f9b1d3e5a730
Create Date: 2026-10-15 23:00:00.000000

The primary keys lead with contest_slug, so per-student lookups (student page,
analytics for one student, instructor groups) couldn't use them.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a1c3e5f7b902'
down_revision: Union[str, Sequence[str], None] = 'f9b1d3e5a730'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_results_student_contest', 'results', ['student_id', 'contest_slug'])
    op.create_index('ix_problem_results_student_contest', 'problem_results', ['student_id', 'contest_slug'])


def downgrade() -> None:
    op.drop_index('ix_problem_results_student_contest', table_name='problem_results')
    op.drop_index('ix_results_student_contest', table_name='results')
