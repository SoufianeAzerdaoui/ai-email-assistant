"""Persistence models; Gmail identifiers and send keys are scoped to a user."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    Index, Integer, String, Text, UniqueConstraint, Uuid, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Record:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class User(Record, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    token_version: Mapped[int] = mapped_column(Integer, server_default="0")

    threads: Mapped[list[Thread]] = relationship(back_populates="user")
    emails: Mapped[list[Email]] = relationship(back_populates="user")
    replies: Mapped[list[Reply]] = relationship(back_populates="user")
    sync_executions: Mapped[list[SyncExecution]] = relationship(back_populates="user")
    sync_state: Mapped[SyncState | None] = relationship(back_populates="user")
    workflow_errors: Mapped[list[WorkflowError]] = relationship(back_populates="user")


class Thread(Record, Base):
    __tablename__ = "threads"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_thread_id", name="uq_threads_user_gmail"),
        UniqueConstraint("id", "user_id", name="uq_threads_id_user"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    gmail_thread_id: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(Text, server_default="")

    user: Mapped[User] = relationship(back_populates="threads")
    emails: Mapped[list[Email]] = relationship(
        back_populates="thread", foreign_keys="Email.thread_id",
        order_by="Email.received_at",
    )


class Email(Record, Base):
    __tablename__ = "emails"
    __table_args__ = (
        UniqueConstraint("user_id", "gmail_message_id", name="uq_emails_user_gmail"),
        UniqueConstraint("id", "user_id", name="uq_emails_id_user"),
        ForeignKeyConstraint(
            ["thread_id", "user_id"], ["threads.id", "threads.user_id"],
            name="fk_emails_thread_user",
        ),
        CheckConstraint("priority BETWEEN 1 AND 3", name="priority"),
        CheckConstraint(
            "category IN ('client', 'facture', 'rendez-vous', 'newsletter', "
            "'spam probable', 'autre')", name="category",
        ),
        CheckConstraint(
            "status IN ('pending', 'draft_ready', 'replied', 'ignored')", name="status",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    thread_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    gmail_message_id: Mapped[str] = mapped_column(String(255))
    message_id: Mapped[str | None] = mapped_column(Text)
    sender: Mapped[str] = mapped_column(Text)
    recipients: Mapped[list[str]] = mapped_column(JSONB)
    subject: Mapped[str] = mapped_column(Text, server_default="")
    body_text: Mapped[str] = mapped_column(Text, server_default="")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[str | None] = mapped_column(String(32))
    priority: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    expected_action: Mapped[str | None] = mapped_column(Text)
    needs_review: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(32), server_default="pending")

    user: Mapped[User] = relationship(back_populates="emails")
    thread: Mapped[Thread] = relationship(
        back_populates="emails", foreign_keys=[thread_id],
    )
    drafts: Mapped[list[Draft]] = relationship(back_populates="email")
    replies: Mapped[list[Reply]] = relationship(
        back_populates="email", foreign_keys="Reply.email_id",
    )


class Draft(Record, Base):
    __tablename__ = "drafts"
    __table_args__ = (
        UniqueConstraint("id", "email_id", name="uq_drafts_id_email"),
        CheckConstraint("tone IN ('formal', 'neutral', 'short')", name="tone"),
    )

    email_id: Mapped[UUID] = mapped_column(ForeignKey("emails.id"), index=True)
    body_text: Mapped[str] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(String(16), server_default="neutral")
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    email: Mapped[Email] = relationship(back_populates="drafts")
    replies: Mapped[list[Reply]] = relationship(
        back_populates="draft", foreign_keys="Reply.draft_id",
    )


class DraftGeneration(Record, Base):
    __tablename__ = "draft_generations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["email_id", "user_id"], ["emails.id", "emails.user_id"],
            name="fk_draft_generations_email_user",
        ),
        ForeignKeyConstraint(
            ["draft_id", "email_id"], ["drafts.id", "drafts.email_id"],
            name="fk_draft_generations_draft_email",
        ),
        CheckConstraint("tone IN ('formal', 'neutral', 'short')", name="tone"),
        CheckConstraint(
            "status IN ('pending', 'generating', 'ready', 'failed')", name="status"
        ),
        UniqueConstraint("draft_id", name="uq_draft_generations_draft_id"),
        Index(
            "uq_draft_generations_active",
            "user_id",
            "email_id",
            "tone",
            unique=True,
            postgresql_where=text("status IN ('pending', 'generating')"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    email_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    draft_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    tone: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

class Reply(Record, Base):
    __tablename__ = "replies"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_replies_user_idempotency"),
        UniqueConstraint("user_id", "gmail_message_id", name="uq_replies_user_gmail"),
        ForeignKeyConstraint(
            ["email_id", "user_id"], ["emails.id", "emails.user_id"],
            name="fk_replies_email_user",
        ),
        ForeignKeyConstraint(
            ["draft_id", "email_id"], ["drafts.id", "drafts.email_id"],
            name="fk_replies_draft_email",
        ),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key"),
        CheckConstraint("status IN ('pending', 'sending', 'sent', 'failed')", name="status"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    email_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    draft_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    body_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    gmail_message_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="replies")
    email: Mapped[Email] = relationship(back_populates="replies", foreign_keys=[email_id])
    draft: Mapped[Draft | None] = relationship(
        back_populates="replies", foreign_keys=[draft_id],
    )


class SyncExecution(Record, Base):
    __tablename__ = "sync_executions"
    __table_args__ = (
        UniqueConstraint("id", "user_id", name="uq_sync_executions_id_user"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_sync_executions_user_key"),
        CheckConstraint("status IN ('running', 'succeeded', 'failed')", name="status"),
        CheckConstraint("imported_count >= 0", name="imported_count"),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), server_default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cursor_before: Mapped[str | None] = mapped_column(Text)
    cursor_after: Mapped[str | None] = mapped_column(Text)
    imported_count: Mapped[int] = mapped_column(Integer, server_default="0")

    user: Mapped[User] = relationship(back_populates="sync_executions")
    workflow_errors: Mapped[list[WorkflowError]] = relationship(
        back_populates="sync_execution", foreign_keys="WorkflowError.sync_execution_id",
    )
    sync_states: Mapped[list[SyncState]] = relationship(
        back_populates="last_successful_execution",
        foreign_keys="SyncState.last_successful_execution_id",
    )


class SyncState(Base):
    __tablename__ = "sync_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["last_successful_execution_id", "user_id"],
            ["sync_executions.id", "sync_executions.user_id"],
            name="fk_sync_states_execution_user",
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(Text)
    last_successful_execution_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="sync_state")
    last_successful_execution: Mapped[SyncExecution | None] = relationship(
        back_populates="sync_states", foreign_keys=[last_successful_execution_id],
    )


class WorkflowError(Record, Base):
    __tablename__ = "workflow_errors"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_workflow_errors_user_key"),
        ForeignKeyConstraint(
            ["sync_execution_id", "user_id"],
            ["sync_executions.id", "sync_executions.user_id"],
            name="fk_workflow_errors_execution_user",
        ),
        CheckConstraint("length(trim(idempotency_key)) > 0", name="idempotency_key"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"), index=True)
    sync_execution_id: Mapped[UUID | None] = mapped_column(Uuid, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    workflow_name: Mapped[str] = mapped_column(String(255))
    node_name: Mapped[str | None] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="workflow_errors")
    sync_execution: Mapped[SyncExecution | None] = relationship(
        back_populates="workflow_errors", foreign_keys=[sync_execution_id],
    )
