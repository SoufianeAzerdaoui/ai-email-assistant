"""Add user authentication fields.

Revision ID: 0002
Revises: 0001
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False)
    )
    op.add_column(
        "users", sa.Column("token_version", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
    op.drop_column("users", "is_admin")
