"""Authenticated daily mailbox summary without external AI calls."""

from datetime import date as Date, datetime, time, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Email, User
from app.summary_schemas import DailySummaryResponse, PriorityEmailResponse


router = APIRouter(tags=["summary"])

PRIORITY_LABELS = {1: "basse", 2: "moyenne", 3: "haute"}
CATEGORY_LABELS = {
    "client": "client",
    "facture": "facture",
    "rendez-vous": "rendez-vous",
    "newsletter": "newsletter",
    "spam probable": "spam probable",
    "autre": "autre",
}


def priority_reason(email: Email) -> str:
    priority = PRIORITY_LABELS.get(email.priority, "non définie")
    category = CATEGORY_LABELS.get(email.category or "", "non classée")
    reason = f"Priorité {priority} ({email.priority or 0}/3), catégorie « {category} »"
    if email.expected_action:
        reason += f" ; action attendue : {email.expected_action.rstrip('.')}"
    else:
        reason += " ; ce message reste à traiter"
    if email.needs_review:
        reason += " ; classification à vérifier"
    return reason + "."


def daily_summary_text(total: int, pending: int, replied: int, draft_ready: int, day: Date) -> str:
    formatted_date = day.strftime("%d/%m/%Y")
    if total == 0:
        return f"Aucun e-mail reçu le {formatted_date}."
    email_word = "e-mail" if total == 1 else "e-mails"
    return (
        f"{total} {email_word} reçu{'s' if total > 1 else ''} le {formatted_date} : "
        f"{pending} à traiter, {replied} répondu{'s' if replied > 1 else ''} et "
        f"{draft_ready} brouillon{'s' if draft_ready > 1 else ''} prêt{'s' if draft_ready > 1 else ''}."
    )


@router.get("/summary", response_model=DailySummaryResponse)
def get_daily_summary(
    date: Date,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    day_start = datetime.combine(date, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    conditions = (
        Email.user_id == current_user.id,
        Email.received_at >= day_start,
        Email.received_at < day_end,
    )

    counts = db.execute(select(
        func.count(Email.id).label("total"),
        func.count(Email.id).filter(Email.status == "pending").label("pending"),
        func.count(Email.id).filter(Email.status == "replied").label("replied"),
        func.count(Email.id).filter(Email.status == "draft_ready").label("draft_ready"),
    ).where(*conditions)).one()

    priority_emails = db.scalars(
        select(Email)
        .where(*conditions, Email.status == "pending")
        .order_by(Email.priority.desc().nullslast(), Email.received_at.desc(), Email.id.desc())
        .limit(5)
    ).all()

    return DailySummaryResponse(
        date=date,
        total_emails=counts.total,
        pending_emails=counts.pending,
        replied_emails=counts.replied,
        draft_ready_emails=counts.draft_ready,
        top_priority_emails=[
            PriorityEmailResponse(
                id=email.id,
                thread_id=email.thread_id,
                sender=email.sender,
                subject=email.subject,
                received_at=email.received_at,
                category=email.category,
                priority=email.priority,
                reason=priority_reason(email),
            )
            for email in priority_emails
        ],
        daily_summary=daily_summary_text(
            counts.total, counts.pending, counts.replied, counts.draft_ready, date
        ),
    )
