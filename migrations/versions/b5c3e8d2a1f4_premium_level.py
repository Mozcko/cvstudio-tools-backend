"""Premium level: users.premium_until, promo_codes.premium

Revision ID: b5c3e8d2a1f4
Revises: a4d2f7c1b9e3
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5c3e8d2a1f4'
down_revision: Union[str, None] = 'a4d2f7c1b9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('premium_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        'promo_codes',
        sa.Column('premium', sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # Nobody loses what they already have. Existing passes do not record which purchase each
    # day came from, so this errs on the generous side: a timed pass is premium for all its
    # remaining time when the user bought Active Hunt in the last 90 days (and was not refunded)
    # or redeemed a code worth a month or more. Lifetime users are premium without a date.
    # Passes granted by hand with the upgrade script are left as plain Pro.
    op.execute("UPDATE promo_codes SET premium = true WHERE granted_days >= 30")
    op.execute(
        """
        UPDATE users AS u
        SET premium_until = u.pro_expires_at
        WHERE u.is_pro
          AND u.pro_expires_at IS NOT NULL
          AND (
            EXISTS (
              SELECT 1 FROM payments p
              WHERE p.user_id = u.id
                AND p.plan = '30'
                AND p.refunded_at IS NULL
                AND p.created_at > now() - interval '90 days'
            )
            OR EXISTS (
              SELECT 1 FROM promo_redemptions r
              JOIN promo_codes c ON c.id = r.promo_id
              WHERE r.user_id = u.id AND c.granted_days >= 30
            )
          )
        """
    )


def downgrade() -> None:
    op.drop_column('promo_codes', 'premium')
    op.drop_column('users', 'premium_until')
