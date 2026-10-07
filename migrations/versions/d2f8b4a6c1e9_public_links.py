"""Public CV links and their view statistics

Revision ID: d2f8b4a6c1e9
Revises: c7a9d3f1e2b6
Create Date: 2026-10-07 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd2f8b4a6c1e9'
down_revision: Union[str, None] = 'c7a9d3f1e2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'public_links',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('cv_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('show_email', sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column('show_phone', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('indexable', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('views_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['cv_id'], ['cvs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cv_id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_public_links_user_id', 'public_links', ['user_id'], unique=False)

    op.create_table(
        'link_views',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('link_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('viewed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('visitor', sa.String(), nullable=False),
        sa.Column('referrer_host', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['link_id'], ['public_links.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_link_views_link_viewed', 'link_views', ['link_id', 'viewed_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_link_views_link_viewed', table_name='link_views')
    op.drop_table('link_views')
    op.drop_index('ix_public_links_user_id', table_name='public_links')
    op.drop_table('public_links')
