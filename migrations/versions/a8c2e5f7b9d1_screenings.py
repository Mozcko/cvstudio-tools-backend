"""Recruiter screenings and their candidates

Revision ID: a8c2e5f7b9d1
Revises: f6b1d8e3a2c7
Create Date: 2026-10-08 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a8c2e5f7b9d1'
down_revision: Union[str, None] = 'f6b1d8e3a2c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'screenings',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('job_description', sa.Text(), nullable=False),
        sa.Column('language', sa.String(), nullable=False),
        sa.Column('rubric', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_screenings_user_created', 'screenings', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_screenings_expires_at', 'screenings', ['expires_at'], unique=False)

    op.create_table(
        'screening_candidates',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('screening_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('file_name', sa.String(), server_default='', nullable=False),
        sa.Column('contact', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('text_hash', sa.String(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('missing_musts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('flagged', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('result', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('note', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['screening_id'], ['screenings.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('screening_id', 'text_hash', name='uq_screening_candidates_text'),
    )
    op.create_index('ix_screening_candidates_screening', 'screening_candidates', ['screening_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_screening_candidates_screening', table_name='screening_candidates')
    op.drop_table('screening_candidates')
    op.drop_index('ix_screenings_expires_at', table_name='screenings')
    op.drop_index('ix_screenings_user_created', table_name='screenings')
    op.drop_table('screenings')
