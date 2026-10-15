"""Authenticated read-only email and conversation endpoints."""

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.email_schemas import EmailPageResponse, EmailResponse, ThreadResponse
from app.models import Email, Thread, User


router = APIRouter(tags=["emails"])

Category = Literal["client", "facture", "rendez-vous", "newsletter", "spam probable", "autre"]
EmailStatus = Literal["pending", "draft_ready", "replied", "ignored"]


def _contains(value: str) -> str:
    """Escape SQL wildcard characters so search terms remain literal."""
    return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.get("/emails", response_model=EmailPageResponse)
def list_emails(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    category: Category | None = None,
    priority: Annotated[int | None, Query(ge=1, le=3)] = None,
    status_filter: Annotated[EmailStatus | None, Query(alias="status")] = None,
    sender: Annotated[str | None, Query(min_length=1, max_length=320)] = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=500)] = None,
):
    date_from = _as_utc(date_from)
    date_to = _as_utc(date_to)
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date_from must be earlier than or equal to date_to",
        )

    conditions = [Email.user_id == current_user.id]
    if category is not None:
        conditions.append(Email.category == category)
    if priority is not None:
        conditions.append(Email.priority == priority)
    if status_filter is not None:
        conditions.append(Email.status == status_filter)
    if sender is not None:
        conditions.append(Email.sender.ilike(_contains(sender), escape="\\"))
    if date_from is not None:
        conditions.append(Email.received_at >= date_from)
    if date_to is not None:
        conditions.append(Email.received_at <= date_to)
    if search is not None:
        pattern = _contains(search)
        conditions.append(or_(
            Email.subject.ilike(pattern, escape="\\"),
            Email.body_text.ilike(pattern, escape="\\"),
        ))

    total = db.scalar(select(func.count()).select_from(Email).where(*conditions)) or 0
    emails = db.scalars(
        select(Email)
        .where(*conditions)
        .order_by(Email.received_at.desc(), Email.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()
    return EmailPageResponse(
        items=[EmailResponse.model_validate(email) for email in emails],
        page=page,
        limit=limit,
        total=total,
    )


@router.get("/emails/{id}", response_model=EmailResponse)
def get_email(
    id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    email = db.scalar(select(Email).where(
        Email.id == id,
        Email.user_id == current_user.id,
    ))
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return email


@router.get("/threads/{id}", response_model=ThreadResponse)
def get_thread(
    id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    thread = db.scalar(select(Thread).where(
        Thread.id == id,
        Thread.user_id == current_user.id,
    ))
    if thread is None:
        raise HTTPException(status_code=404, detail="Thread not found")

    emails = db.scalars(
        select(Email)
        .where(Email.thread_id == thread.id, Email.user_id == current_user.id)
        .order_by(Email.received_at.asc(), Email.id.asc())
    ).all()
    return ThreadResponse(
        id=thread.id,
        subject=thread.subject,
        emails=[EmailResponse.model_validate(email) for email in emails],
    )
