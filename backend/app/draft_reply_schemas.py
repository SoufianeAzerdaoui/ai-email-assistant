"""Validated API contracts for manual drafts and reply requests."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


Tone = Literal["formel", "neutre", "court"]
ReplyStatus = Literal["pending", "sending", "sent", "failed"]


class DraftCreate(BaseModel):
    body_text: str = Field(max_length=100_000)
    tone: Tone = "neutre"

    @field_validator("body_text")
    @classmethod
    def validate_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("body_text must not be empty")
        return value


class DraftUpdate(BaseModel):
    body_text: str | None = Field(default=None, max_length=100_000)
    tone: Tone | None = None

    @field_validator("body_text")
    @classmethod
    def validate_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("body_text must not be empty")
        return value

    @model_validator(mode="after")
    def require_change(self):
        if self.body_text is None and self.tone is None:
            raise ValueError("body_text or tone must be provided")
        return self


class DraftResponse(BaseModel):
    id: UUID
    email_id: UUID
    body_text: str
    tone: Tone
    generated_by_ai: bool
    created_at: datetime
    updated_at: datetime


class ReplyCreate(BaseModel):
    confirmed: Literal[True]
    idempotency_key: str = Field(min_length=1, max_length=255)
    draft_id: UUID | None = None
    body_text: str | None = Field(default=None, max_length=100_000)

    @field_validator("idempotency_key")
    @classmethod
    def validate_idempotency_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("idempotency_key must not be empty")
        return value

    @field_validator("body_text")
    @classmethod
    def validate_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("body_text must not be empty")
        return value

    @model_validator(mode="after")
    def require_content(self):
        if self.draft_id is None and self.body_text is None:
            raise ValueError("draft_id or body_text must be provided")
        return self


class ReplyResponse(BaseModel):
    id: UUID
    email_id: UUID
    thread_id: UUID
    draft_id: UUID | None
    idempotency_key: str
    body_text: str
    status: ReplyStatus
    created_at: datetime
    sent_at: datetime | None
    error_message: str | None


class GmailSendResult(BaseModel):
    reply_id: UUID
    dispatch_id: UUID
    user_id: UUID
    email_id: UUID
    idempotency_key: str = Field(min_length=1, max_length=255)
    status: Literal["sent", "failed"]
    gmail_message_id: str | None = Field(default=None, max_length=255)
    gmail_thread_id: str | None = Field(default=None, max_length=255)
    error_message: str | None = Field(default=None, max_length=2_000)

    @field_validator(
        "idempotency_key", "gmail_message_id", "gmail_thread_id", "error_message"
    )
    @classmethod
    def strip_result_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_result(self):
        if self.status == "sent":
            if self.gmail_message_id is None or self.gmail_thread_id is None:
                raise ValueError(
                    "gmail_message_id and gmail_thread_id are required when status is sent"
                )
            if self.error_message is not None:
                raise ValueError("error_message is only accepted when status is failed")
        else:
            if self.error_message is None:
                raise ValueError("error_message is required when status is failed")
            if self.gmail_message_id is not None or self.gmail_thread_id is not None:
                raise ValueError("Gmail identifiers are only accepted when status is sent")
        return self
