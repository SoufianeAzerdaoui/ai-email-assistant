"""Response schemas for the daily email summary."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class PriorityEmailResponse(BaseModel):
    id: UUID
    thread_id: UUID
    sender: str
    subject: str
    received_at: datetime
    category: str | None
    priority: int | None
    reason: str


class DailySummaryResponse(BaseModel):
    date: date
    total_emails: int
    pending_emails: int
    replied_emails: int
    draft_ready_emails: int
    top_priority_emails: list[PriorityEmailResponse]
    daily_summary: str
