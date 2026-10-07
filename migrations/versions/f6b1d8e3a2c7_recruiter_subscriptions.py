"""Recruiter subscriptions

Revision ID: f6b1d8e3a2c7
Revises: e4a7c9b2d5f1
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6b1d8e3a2c7'
down_revision: Union[str, None] = 'e4a7c9b2d5f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'recruiter_subscriptions',
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('plan', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('stripe_customer_id', sa.String(), nullable=True),
        sa.Column('stripe_subscription_id', sa.String(), nullable=True),
        sa.Column('last_event_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('monthly_quota', sa.Integer(), nullable=True),
        sa.Column('retention_days', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'),
        sa.UniqueConstraint('stripe_subscription_id'),
    )
    op.create_index(
        'ix_recruiter_subscriptions_stripe_customer_id', 'recruiter_subscriptions', ['stripe_customer_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_recruiter_subscriptions_stripe_customer_id', table_name='recruiter_subscriptions')
    op.drop_table('recruiter_subscriptions')
