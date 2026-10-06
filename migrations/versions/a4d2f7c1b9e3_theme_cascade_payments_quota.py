"""CV theme, cascading deletes, promo redemptions, payments, AI usage

Revision ID: a4d2f7c1b9e3
Revises: 9db7771a15bc
Create Date: 2026-10-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a4d2f7c1b9e3'
down_revision: Union[str, None] = '9db7771a15bc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cvs', sa.Column('theme', sa.String(), nullable=True))

    # cvs.user_id -> users.id now cascades (the constraint name differs between databases)
    inspector = sa.inspect(op.get_bind())
    for fk in inspector.get_foreign_keys('cvs'):
        if fk.get('referred_table') == 'users' and fk.get('name'):
            op.drop_constraint(fk['name'], 'cvs', type_='foreignkey')
    op.create_foreign_key('cvs_user_id_fkey', 'cvs', 'users', ['user_id'], ['id'], ondelete='CASCADE')

    op.create_table(
        'promo_redemptions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('promo_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['promo_id'], ['promo_codes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('promo_id', 'user_id', name='uq_promo_redemptions_promo_user'),
    )
    op.create_index('ix_promo_redemptions_user_id', 'promo_redemptions', ['user_id'], unique=False)

    op.create_table(
        'payments',
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('plan', sa.String(), nullable=False),
        sa.Column('payment_intent', sa.String(), nullable=True),
        sa.Column('granted_days', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('refunded_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('session_id'),
    )
    op.create_index('ix_payments_user_id', 'payments', ['user_id'], unique=False)
    op.create_index('ix_payments_payment_intent', 'payments', ['payment_intent'], unique=False)

    op.create_table(
        'ai_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ai_requests_user_created', 'ai_requests', ['user_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_table('ai_requests')
    op.drop_table('payments')
    op.drop_table('promo_redemptions')
    op.drop_constraint('cvs_user_id_fkey', 'cvs', type_='foreignkey')
    op.create_foreign_key('cvs_user_id_fkey', 'cvs', 'users', ['user_id'], ['id'])
    op.drop_column('cvs', 'theme')
