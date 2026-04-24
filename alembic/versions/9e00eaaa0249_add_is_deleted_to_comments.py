"""add is_deleted to comments

Revision ID: 9e00eaaa0249
Revises: ff8b30727d82
Create Date: 2026-04-24 23:30:25.148078

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9e00eaaa0249'
down_revision: Union[str, Sequence[str], None] = 'ff8b30727d82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('comments', sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('comments', 'is_deleted')
