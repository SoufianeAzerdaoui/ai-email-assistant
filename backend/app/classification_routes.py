"""Internal webhook used by n8n to persist validated classifications."""

from hmac import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.classification_schemas import (
    ClassificationCreate,
    ClassificationResponse,
    WorkflowErrorCreate,
    WorkflowErrorResponse,
)
from app.config import get_webhook_secret
from app.database import get_db
from app.models import Email, User, WorkflowError


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
        ).with_for_update()
    )
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")

    current = (
        email.category,
        email.priority,
        email.summary,
        email.expected_action,
        email.needs_review,
    )
    incoming = (
        payload.category,
        payload.priority,
        payload.summary,
        payload.expected_action,
        payload.needs_review,
    )
    if all(value is not None for value in current):
        if current != incoming:
            raise HTTPException(status_code=409, detail="Email already has a different classification")
        return ClassificationResponse(
            email_id=email.id,
            category=email.category,
            priority=email.priority,
            summary=email.summary,
            expected_action=email.expected_action,
            needs_review=email.needs_review,
        )

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


ERROR_MESSAGES = {
    "invalid_gemini_output": "Gemini returned invalid classification output",
    "gemini_unavailable": "Gemini classification failed after bounded retries",
    "classification_callback_failed": "Classification callback failed after bounded retries",
    "classification_dispatch_failed": "Classification workflow dispatch failed",
    "workflow_failed": "n8n workflow execution failed",
}


@router.post(
    "/workflow-errors",
    response_model=WorkflowErrorResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
def record_workflow_error(
    payload: WorkflowErrorCreate,
    db: Annotated[Session, Depends(get_db)],
):
    if db.get(User, payload.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if payload.email_id is not None and db.scalar(select(Email.id).where(
        Email.id == payload.email_id,
        Email.user_id == payload.user_id,
    )) is None:
        raise HTTPException(status_code=404, detail="Email not found")

    details = {
        "error_type": payload.error_type,
        "email_id": str(payload.email_id) if payload.email_id else None,
        "status_code": payload.status_code,
        "attempt": payload.attempt,
    }
    inserted_id = db.execute(
        insert(WorkflowError)
        .values(
            user_id=payload.user_id,
            idempotency_key=payload.idempotency_key,
            workflow_name=payload.workflow_name,
            node_name=payload.node_name,
            message=ERROR_MESSAGES[payload.error_type],
            details=details,
        )
        .on_conflict_do_nothing(
            index_elements=[WorkflowError.user_id, WorkflowError.idempotency_key]
        )
        .returning(WorkflowError.id)
    ).scalar_one_or_none()
    created = inserted_id is not None
    workflow_error = db.scalar(select(WorkflowError).where(
        WorkflowError.user_id == payload.user_id,
        WorkflowError.idempotency_key == payload.idempotency_key,
    ))
    if workflow_error is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to resolve workflow error")
    if (
        workflow_error.workflow_name != payload.workflow_name
        or workflow_error.node_name != payload.node_name
        or workflow_error.details != details
    ):
        db.rollback()
        raise HTTPException(status_code=409, detail="Error key already used for different data")
    db.commit()
    return WorkflowErrorResponse(id=workflow_error.id, created=created)
