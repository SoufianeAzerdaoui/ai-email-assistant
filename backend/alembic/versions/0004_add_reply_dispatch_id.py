"""Track individual Gmail dispatch attempts.

Revision ID: 0004
Revises: 0003
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("replies", sa.Column("dispatch_id", sa.Uuid(), nullable=True))


def downgrade() -> None:
    op.drop_column("replies", "dispatch_id")
