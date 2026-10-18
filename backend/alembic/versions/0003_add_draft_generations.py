"""Add asynchronous AI draft generations.

Revision ID: 0003
Revises: 0002
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "draft_generations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("email_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid(), nullable=True),
        sa.Column("tone", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'generating', 'ready', 'failed')",
            name=op.f("ck_draft_generations_status"),
        ),
        sa.CheckConstraint(
            "tone IN ('formal', 'neutral', 'short')",
            name=op.f("ck_draft_generations_tone"),
        ),
        sa.ForeignKeyConstraint(
            ["draft_id", "email_id"],
            ["drafts.id", "drafts.email_id"],
            name="fk_draft_generations_draft_email",
        ),
        sa.ForeignKeyConstraint(
            ["email_id", "user_id"],
            ["emails.id", "emails.user_id"],
            name="fk_draft_generations_email_user",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_draft_generations_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_generations")),
        sa.UniqueConstraint("draft_id", name=op.f("uq_draft_generations_draft_id")),
    )
    op.create_index(
        op.f("ix_draft_generations_draft_id"), "draft_generations", ["draft_id"], unique=False
    )
    op.create_index(
        op.f("ix_draft_generations_email_id"), "draft_generations", ["email_id"], unique=False
    )
    op.create_index(
        op.f("ix_draft_generations_user_id"), "draft_generations", ["user_id"], unique=False
    )
    op.create_index(
        "uq_draft_generations_active",
        "draft_generations",
        ["user_id", "email_id", "tone"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'generating')"),
    )


def downgrade() -> None:
    op.drop_index("uq_draft_generations_active", table_name="draft_generations")
    op.drop_index(op.f("ix_draft_generations_user_id"), table_name="draft_generations")
    op.drop_index(op.f("ix_draft_generations_email_id"), table_name="draft_generations")
    op.drop_index(op.f("ix_draft_generations_draft_id"), table_name="draft_generations")
    op.drop_table("draft_generations")
