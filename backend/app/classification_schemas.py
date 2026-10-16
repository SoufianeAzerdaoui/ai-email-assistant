"""Validated contracts for classifications received from internal workflows."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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
