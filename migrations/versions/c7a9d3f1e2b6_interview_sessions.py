"""Mock interview sessions

Revision ID: c7a9d3f1e2b6
Revises: b5c3e8d2a1f4
Create Date: 2026-10-07 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7a9d3f1e2b6'
down_revision: Union[str, None] = 'b5c3e8d2a1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'interview_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), server_default='', nullable=False),
        sa.Column('language', sa.String(), nullable=False),
        sa.Column('job_description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), server_default='active', nullable=False),
        sa.Column('questions', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('turns', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('report', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('audio_count', sa.Integer(), server_default='0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_interview_sessions_user_created', 'interview_sessions', ['user_id', 'created_at'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_interview_sessions_user_created', table_name='interview_sessions')
    op.drop_table('interview_sessions')
