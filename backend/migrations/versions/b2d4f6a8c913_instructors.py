# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""instructors: display name and student assignments

Revision ID: b2d4f6a8c913
Revises: a7c3e91b2d40
Create Date: 2026-10-15 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c913'
down_revision: Union[str, Sequence[str], None] = 'a7c3e91b2d40'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('display_name', sa.String(length=200), nullable=True))
    op.create_table(
        'instructor_colleges',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('college_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['college_id'], ['colleges.id'], name=op.f('fk_instructor_colleges_college_id_colleges'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_instructor_colleges_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'college_id', name=op.f('pk_instructor_colleges')),
    )
    op.create_table(
        'instructor_students',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], name=op.f('fk_instructor_students_student_id_students'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_instructor_students_user_id_users'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'student_id', name=op.f('pk_instructor_students')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('instructor_students')
    op.drop_table('instructor_colleges')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('display_name')
