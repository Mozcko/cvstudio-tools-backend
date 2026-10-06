"""Baseline schema: users, cvs, promo_codes

Originally an empty revision ("Add promo codes table"); the tables were created by
`Base.metadata.create_all` at application startup. It now creates them when they are
missing, so `alembic upgrade head` works on an empty database as well as on one that
the application already populated.

Revision ID: c19b7a9812e7
Revises:
Create Date: 2026-06-06 06:31:26.331154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c19b7a9812e7'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if 'users' not in existing:
        op.create_table(
            'users',
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('email', sa.String(), nullable=True),
            sa.Column('is_pro', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_users_id', 'users', ['id'], unique=False)
        op.create_index('ix_users_email', 'users', ['email'], unique=True)

    if 'cvs' not in existing:
        op.create_table(
            'cvs',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('title', sa.String(), nullable=False),
            sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column('language', sa.String(), server_default='ES', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='cvs_user_id_fkey'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_cvs_user_id', 'cvs', ['user_id'], unique=False)

    if 'promo_codes' not in existing:
        op.create_table(
            'promo_codes',
            sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column('code', sa.String(), nullable=False),
            sa.Column('max_uses', sa.Integer(), nullable=True),
            sa.Column('used_count', sa.Integer(), nullable=True),
            sa.Column('granted_days', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_promo_codes_code', 'promo_codes', ['code'], unique=True)


def downgrade() -> None:
    op.drop_table('promo_codes')
    op.drop_table('cvs')
    op.drop_table('users')
