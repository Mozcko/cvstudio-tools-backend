"""Add pro_expires_at to User

Revision ID: 9db7771a15bc
Revises: c19b7a9812e7
Create Date: 2026-06-06 06:34:40.484454

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9db7771a15bc'
down_revision: Union[str, None] = 'c19b7a9812e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guarded: databases created by the old startup `create_all` already have the column
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('users')}
    if 'pro_expires_at' not in columns:
        op.add_column('users', sa.Column('pro_expires_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'pro_expires_at')
