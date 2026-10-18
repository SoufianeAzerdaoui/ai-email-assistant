"""Validated contracts for classifications received from internal workflows."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


Category = Literal[
    "client",
    "facture",
    "rendez-vous",
    "newsletter",
    "spam probable",
    "autre",
]


class ClassificationCreate(BaseModel):
    user_id: UUID
    email_id: UUID
    category: Category
    priority: int = Field(ge=1, le=3)
    summary: str = Field(min_length=1, max_length=1_000)
    expected_action: str = Field(min_length=1, max_length=2_000)
    needs_review: bool = False

    @field_validator("summary", "expected_action")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value


class ClassificationResponse(BaseModel):
    email_id: UUID
    category: Category
    priority: int
    summary: str
    expected_action: str
    needs_review: bool


WorkflowErrorType = Literal[
    "invalid_gemini_output",
    "gemini_unavailable",
    "classification_callback_failed",
    "classification_dispatch_failed",
    "workflow_failed",
]


class WorkflowErrorCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    email_id: UUID | None = None
    idempotency_key: str = Field(min_length=1, max_length=255)
    workflow_name: str = Field(min_length=1, max_length=255)
    node_name: str | None = Field(default=None, max_length=255)
    error_type: WorkflowErrorType
    status_code: int | None = Field(default=None, ge=100, le=599)
    attempt: int | None = Field(default=None, ge=0, le=10)

    @field_validator("idempotency_key", "workflow_name", "node_name")
    @classmethod
    def strip_error_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value


class WorkflowErrorResponse(BaseModel):
    id: UUID
    created: bool
