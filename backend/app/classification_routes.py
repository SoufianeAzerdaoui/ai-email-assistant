"""Internal webhook used by n8n to persist validated classifications."""

from hmac import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.classification_schemas import ClassificationCreate, ClassificationResponse
from app.config import get_webhook_secret
from app.database import get_db
from app.models import Email


router = APIRouter(prefix="/internal/webhooks", tags=["internal"])


def verify_webhook_secret(
    supplied_secret: Annotated[str | None, Header(alias="X-Webhook-Secret")] = None,
) -> None:
    expected_secret = get_webhook_secret()
    if supplied_secret is None or not compare_digest(
        supplied_secret.encode("utf-8"), expected_secret.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook credentials")


@router.post(
    "/classification",
    response_model=ClassificationResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
def receive_classification(
    payload: ClassificationCreate,
    db: Annotated[Session, Depends(get_db)],
):
    email = db.scalar(
        select(Email).where(
            Email.id == payload.email_id,
            Email.user_id == payload.user_id,
        )
    )
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")

    email.category = payload.category
    email.priority = payload.priority
    email.summary = payload.summary
    email.expected_action = payload.expected_action
    email.needs_review = payload.needs_review
    db.commit()

    return ClassificationResponse(
        email_id=email.id,
        category=email.category,
        priority=email.priority,
        summary=email.summary,
        expected_action=email.expected_action,
        needs_review=email.needs_review,
    )
