"""Public response schemas for email and thread endpoints."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EmailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    thread_id: UUID
    sender: str
    recipients: list[str]
    subject: str
    body_text: str
    received_at: datetime
    category: str | None
    priority: int | None
    summary: str | None
    expected_action: str | None
    needs_review: bool
    status: str


class EmailPageResponse(BaseModel):
    items: list[EmailResponse]
    page: int
    limit: int
    total: int


class ThreadResponse(BaseModel):
    id: UUID
    subject: str
    emails: list[EmailResponse]
