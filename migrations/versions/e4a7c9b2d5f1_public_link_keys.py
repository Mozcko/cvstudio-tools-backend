"""Public links are identified by a random key; names no longer have to be unique

Revision ID: e4a7c9b2d5f1
Revises: d2f8b4a6c1e9
Create Date: 2026-10-07 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4a7c9b2d5f1'
down_revision: Union[str, None] = 'd2f8b4a6c1e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('public_links', sa.Column('key', sa.String(), nullable=True))
    # Links created before keys existed get one now (8 characters of a-z0-9)
    op.execute(
        "UPDATE public_links SET key = substr(md5(random()::text || id::text || clock_timestamp()::text), 1, 8)"
    )
    op.alter_column('public_links', 'key', nullable=False)
    op.create_unique_constraint('public_links_key_key', 'public_links', ['key'])
    op.drop_constraint('public_links_slug_key', 'public_links', type_='unique')


def downgrade() -> None:
    # Names may repeat by now: make them unique again before restoring the constraint
    op.execute("UPDATE public_links SET slug = left(slug, 31) || '-' || key")
    op.create_unique_constraint('public_links_slug_key', 'public_links', ['slug'])
    op.drop_constraint('public_links_key_key', 'public_links', type_='unique')
    op.drop_column('public_links', 'key')
