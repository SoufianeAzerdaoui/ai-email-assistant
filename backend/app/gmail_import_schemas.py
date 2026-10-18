"""Validated contracts for Gmail messages normalized by n8n."""

from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class GmailMessageImport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gmail_message_id: str = Field(min_length=1, max_length=255)
    gmail_thread_id: str = Field(min_length=1, max_length=255)
    message_id: str | None = Field(default=None, max_length=998)
    sender: str = Field(min_length=1, max_length=2_000)
    recipients: list[str] = Field(max_length=100)
    subject: str = Field(max_length=10_000)
    body_text: str = Field(max_length=5_000_000)
    body_html: str | None = Field(default=None, max_length=5_000_000)
    received_at: datetime

    @field_validator("gmail_message_id", "gmail_thread_id", "sender")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("message_id")
    @classmethod
    def strip_optional_message_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("recipients")
    @classmethod
    def validate_recipients(cls, recipients: list[str]) -> list[str]:
        normalized = [recipient.strip() for recipient in recipients]
        if any(not recipient or len(recipient) > 2_000 for recipient in normalized):
            raise ValueError("recipients must contain non-empty address strings")
        return normalized

    @field_validator("received_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("received_at must include a timezone")
        return value.astimezone(timezone.utc)


class GmailImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    messages: list[GmailMessageImport] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_unique_message_ids(self):
        message_ids = [message.gmail_message_id for message in self.messages]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("gmail_message_id values must be unique within a batch")
        return self


class GmailImportResponse(BaseModel):
    user_id: UUID
    received_count: int
    imported_count: int
    duplicate_count: int
    repaired_count: int
    created_thread_count: int


class GmailSyncStateResponse(BaseModel):
    user_id: UUID
    cursor: str | None
    last_synced_at: datetime | None


class GmailSyncCommitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    cursor_before: str | None = Field(default=None, max_length=2_000)
    cursor_after: str = Field(min_length=1, max_length=2_000)
    idempotency_key: str = Field(min_length=1, max_length=255)
    imported_count: int = Field(ge=0)

    @field_validator("cursor_before", "cursor_after", "idempotency_key")
    @classmethod
    def normalize_cursor_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value


class GmailSyncCommitResponse(GmailSyncStateResponse):
    execution_id: UUID
    imported_count: int
