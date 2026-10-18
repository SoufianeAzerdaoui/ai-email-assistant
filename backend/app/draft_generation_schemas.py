"""API contracts for asynchronous AI draft generation."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.draft_reply_schemas import Tone


GenerationStatus = Literal["pending", "generating", "ready", "failed"]


class DraftGenerationCreate(BaseModel):
    tone: Tone = "neutre"


class DraftGenerationResponse(BaseModel):
    id: UUID
    email_id: UUID
    draft_id: UUID | None
    tone: Tone
    status: GenerationStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DraftResult(BaseModel):
    generation_id: UUID
    user_id: UUID
    email_id: UUID
    status: Literal["generating", "ready", "failed"]
    body_text: str | None = Field(default=None, max_length=100_000)
    error_message: str | None = Field(default=None, max_length=2_000)

    @field_validator("body_text", "error_message")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_result(self):
        if self.status == "ready" and self.body_text is None:
            raise ValueError("body_text is required when status is ready")
        if self.status != "ready" and self.body_text is not None:
            raise ValueError("body_text is only accepted when status is ready")
        if self.status == "failed" and self.error_message is None:
            raise ValueError("error_message is required when status is failed")
        if self.status != "failed" and self.error_message is not None:
            raise ValueError("error_message is only accepted when status is failed")
        return self
