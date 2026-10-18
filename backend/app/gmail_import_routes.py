"""Internal, idempotent Gmail ingestion and synchronization state for n8n."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.classification_routes import verify_webhook_secret
from app.database import get_db
from app.email_content import legacy_html_to_readable_text, readable_email_body
from app.gmail_import_schemas import (
    GmailImportRequest,
    GmailImportResponse,
    GmailSyncCommitRequest,
    GmailSyncCommitResponse,
    GmailSyncStateResponse,
)
from app.models import Email, SyncExecution, SyncState, Thread, User


router = APIRouter(prefix="/internal/webhooks", tags=["internal"])


@router.get(
    "/gmail/sync-state/{user_id}",
    response_model=GmailSyncStateResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
def get_gmail_sync_state(
    user_id: UUID,
    db: Annotated[Session, Depends(get_db)],
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    state = db.get(SyncState, user.id)
    return GmailSyncStateResponse(
        user_id=user.id,
        cursor=state.cursor if state else None,
        last_synced_at=state.last_synced_at if state else None,
    )


@router.post(
    "/gmail/sync-state/commit",
    response_model=GmailSyncCommitResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
def commit_gmail_sync_state(
    payload: GmailSyncCommitRequest,
    db: Annotated[Session, Depends(get_db)],
):
    user = db.scalar(
        select(User).where(User.id == payload.user_id).with_for_update()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    existing = db.scalar(
        select(SyncExecution).where(
            SyncExecution.user_id == payload.user_id,
            SyncExecution.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        same_commit = (
            existing.status == "succeeded"
            and existing.cursor_before == payload.cursor_before
            and existing.cursor_after == payload.cursor_after
            and existing.imported_count == payload.imported_count
        )
        if not same_commit:
            raise HTTPException(
                status_code=409,
                detail="Idempotency key already used with different sync data",
            )
        return GmailSyncCommitResponse(
            user_id=payload.user_id,
            cursor=existing.cursor_after,
            last_synced_at=existing.finished_at,
            execution_id=existing.id,
            imported_count=existing.imported_count,
        )

    state = db.get(SyncState, payload.user_id)
    current_cursor = state.cursor if state else None
    if current_cursor != payload.cursor_before:
        raise HTTPException(status_code=409, detail="Gmail sync cursor has changed")

    completed_at = datetime.now(timezone.utc)
    execution = SyncExecution(
        user_id=payload.user_id,
        idempotency_key=payload.idempotency_key,
        status="succeeded",
        finished_at=completed_at,
        cursor_before=payload.cursor_before,
        cursor_after=payload.cursor_after,
        imported_count=payload.imported_count,
    )
    db.add(execution)
    db.flush()
    if state is None:
        state = SyncState(user_id=payload.user_id)
        db.add(state)
    state.cursor = payload.cursor_after
    state.last_successful_execution_id = execution.id
    state.last_synced_at = completed_at
    db.commit()
    return GmailSyncCommitResponse(
        user_id=payload.user_id,
        cursor=payload.cursor_after,
        last_synced_at=completed_at,
        execution_id=execution.id,
        imported_count=payload.imported_count,
    )


@router.post(
    "/gmail/messages",
    response_model=GmailImportResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
def import_gmail_messages(
    payload: GmailImportRequest,
    db: Annotated[Session, Depends(get_db)],
):
    if db.get(User, payload.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")

    imported_count = 0
    repaired_count = 0
    created_thread_count = 0
    thread_ids: dict[str, object] = {}

    for message in payload.messages:
        readable_body = readable_email_body(message.body_text, message.body_html)
        thread_id = thread_ids.get(message.gmail_thread_id)
        if thread_id is None:
            thread_id = db.execute(
                insert(Thread)
                .values(
                    user_id=payload.user_id,
                    gmail_thread_id=message.gmail_thread_id,
                    subject=message.subject,
                )
                .on_conflict_do_nothing(
                    index_elements=[Thread.user_id, Thread.gmail_thread_id]
                )
                .returning(Thread.id)
            ).scalar_one_or_none()
            if thread_id is not None:
                created_thread_count += 1
            else:
                thread_id = db.scalar(
                    select(Thread.id).where(
                        Thread.user_id == payload.user_id,
                        Thread.gmail_thread_id == message.gmail_thread_id,
                    )
                )
            if thread_id is None:
                db.rollback()
                raise HTTPException(status_code=409, detail="Unable to resolve Gmail thread")
            thread_ids[message.gmail_thread_id] = thread_id

        inserted_email_id = db.execute(
            insert(Email)
            .values(
                user_id=payload.user_id,
                thread_id=thread_id,
                gmail_message_id=message.gmail_message_id,
                message_id=message.message_id,
                sender=message.sender,
                recipients=message.recipients,
                subject=message.subject,
                body_text=readable_body,
                received_at=message.received_at,
                status="pending",
            )
            .on_conflict_do_nothing(
                index_elements=[Email.user_id, Email.gmail_message_id]
            )
            .returning(Email.id)
        ).scalar_one_or_none()
        if inserted_email_id is not None:
            imported_count += 1
        else:
            repair_candidates: set[str] = set()
            if message.body_text and readable_body != message.body_text:
                repair_candidates.add(message.body_text)
            if message.body_html:
                legacy_body = legacy_html_to_readable_text(message.body_html)
                if readable_body != message.body_html:
                    repair_candidates.add(message.body_html)
                if readable_body != legacy_body:
                    repair_candidates.add(legacy_body)
            if not repair_candidates:
                continue
            repair_result = db.execute(
                update(Email)
                .where(
                    Email.user_id == payload.user_id,
                    Email.gmail_message_id == message.gmail_message_id,
                    Email.body_text.in_(repair_candidates),
                )
                .values(body_text=readable_body)
            )
            repaired_count += repair_result.rowcount

    db.commit()
    received_count = len(payload.messages)
    return GmailImportResponse(
        user_id=payload.user_id,
        received_count=received_count,
        imported_count=imported_count,
        duplicate_count=received_count - imported_count,
        repaired_count=repaired_count,
        created_thread_count=created_thread_count,
    )
