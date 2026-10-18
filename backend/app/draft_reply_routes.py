"""Manual drafts and human-confirmed, idempotent Gmail reply requests."""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.classification_routes import verify_webhook_secret
from app.database import get_db
from app.draft_reply_schemas import (
    DraftCreate,
    DraftResponse,
    DraftUpdate,
    GmailSendResult,
    ReplyCreate,
    ReplyResponse,
)
from app.models import Draft, Email, Reply, Thread, User
from app.n8n_client import (
    GmailReplyDispatch,
    N8nDispatchError,
    N8nDispatchUncertainError,
    dispatch_gmail_reply,
)


router = APIRouter(tags=["drafts", "replies"])

API_TO_DATABASE_TONE = {"formel": "formal", "neutre": "neutral", "court": "short"}
DATABASE_TO_API_TONE = {value: key for key, value in API_TO_DATABASE_TONE.items()}


def draft_response(draft: Draft) -> DraftResponse:
    return DraftResponse(
        id=draft.id,
        email_id=draft.email_id,
        body_text=draft.body_text,
        tone=DATABASE_TO_API_TONE[draft.tone],
        generated_by_ai=draft.generated_by_ai,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


def reply_response(reply: Reply, thread_id: UUID) -> ReplyResponse:
    return ReplyResponse(
        id=reply.id,
        email_id=reply.email_id,
        thread_id=thread_id,
        draft_id=reply.draft_id,
        idempotency_key=reply.idempotency_key,
        body_text=reply.body_text,
        status=reply.status,
        created_at=reply.created_at,
        sent_at=reply.sent_at,
        error_message=reply.error_message,
    )


def owned_email(db: Session, user_id: UUID, email_id: UUID) -> Email:
    email = db.scalar(select(Email).where(Email.id == email_id, Email.user_id == user_id))
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")
    return email


def owned_draft(db: Session, user_id: UUID, draft_id: UUID) -> Draft:
    draft = db.scalar(
        select(Draft)
        .join(Email, Draft.email_id == Email.id)
        .where(Draft.id == draft_id, Email.user_id == user_id)
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


def original_thread_email(db: Session, user_id: UUID, thread_id: UUID) -> Email:
    email = db.scalar(
        select(Email)
        .where(Email.thread_id == thread_id, Email.user_id == user_id)
        .order_by(Email.received_at, Email.created_at, Email.id)
        .limit(1)
    )
    if email is None:  # The selected email itself normally guarantees this row exists.
        raise HTTPException(status_code=409, detail="Original thread email not found")
    return email


@router.post("/emails/{id}/draft", response_model=DraftResponse, status_code=201)
def create_draft(
    id: UUID,
    payload: DraftCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    email = owned_email(db, current_user.id, id)
    draft = Draft(
        email_id=email.id,
        body_text=payload.body_text,
        tone=API_TO_DATABASE_TONE[payload.tone],
        generated_by_ai=False,
    )
    db.add(draft)
    email.status = "draft_ready"
    db.commit()
    db.refresh(draft)
    return draft_response(draft)


@router.get("/drafts/{id}", response_model=DraftResponse)
def get_draft(
    id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return draft_response(owned_draft(db, current_user.id, id))


@router.put("/drafts/{id}", response_model=DraftResponse)
def update_draft(
    id: UUID,
    payload: DraftUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    draft = owned_draft(db, current_user.id, id)
    if payload.body_text is not None:
        draft.body_text = payload.body_text
    if payload.tone is not None:
        draft.tone = API_TO_DATABASE_TONE[payload.tone]
    db.commit()
    db.refresh(draft)
    return draft_response(draft)


@router.post("/emails/{id}/reply", response_model=ReplyResponse, status_code=201)
def create_reply_request(
    id: UUID,
    payload: ReplyCreate,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    email = owned_email(db, current_user.id, id)
    draft = None
    if payload.draft_id is not None:
        draft = owned_draft(db, current_user.id, payload.draft_id)
        if draft.email_id != email.id:
            raise HTTPException(status_code=422, detail="Draft does not belong to this email")
    body_text = payload.body_text or (draft.body_text if draft else None)
    if body_text is None:  # Guarded by Pydantic, kept explicit for type safety.
        raise HTTPException(status_code=422, detail="Reply content is required")

    reply_id = uuid4()
    inserted_id = db.execute(
        insert(Reply)
        .values(
            id=reply_id,
            user_id=current_user.id,
            email_id=email.id,
            draft_id=draft.id if draft else None,
            idempotency_key=payload.idempotency_key,
            body_text=body_text,
            status="pending",
        )
        .on_conflict_do_nothing(index_elements=[Reply.user_id, Reply.idempotency_key])
        .returning(Reply.id)
    ).scalar_one_or_none()

    created = inserted_id is not None
    reply = db.scalar(select(Reply).where(
        Reply.user_id == current_user.id,
        Reply.idempotency_key == payload.idempotency_key,
    ))
    if reply is None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Unable to resolve idempotent request")
    if (
        reply.email_id != email.id
        or reply.draft_id != (draft.id if draft else None)
        or reply.body_text != body_text
    ):
        db.rollback()
        raise HTTPException(status_code=409, detail="Idempotency key already used for another request")

    if not created:
        response.status_code = status.HTTP_200_OK

    dispatch_id = uuid4()
    claimed = db.execute(
        update(Reply)
        .where(Reply.id == reply.id, Reply.status.in_(("pending", "failed")))
        .values(status="sending", dispatch_id=dispatch_id, error_message=None)
        .returning(Reply.id)
    ).scalar_one_or_none()
    db.commit()

    if claimed is not None:
        thread = db.get(Thread, email.thread_id)
        if thread is None:  # Protected by the email foreign key; kept defensive.
            raise HTTPException(status_code=409, detail="Email thread not found")
        original_email = original_thread_email(db, current_user.id, email.thread_id)
        dispatch_payload: GmailReplyDispatch = {
            "reply_id": str(reply.id),
            "dispatch_id": str(dispatch_id),
            "user_id": str(current_user.id),
            "email_id": str(email.id),
            "idempotency_key": reply.idempotency_key,
            "gmail_message_id": original_email.gmail_message_id,
            "gmail_thread_id": thread.gmail_thread_id,
            "rfc_message_id": original_email.message_id,
            "recipient": original_email.sender,
            "subject": email.subject,
            "body_text": reply.body_text,
        }
        try:
            dispatch_gmail_reply(dispatch_payload)
        except N8nDispatchUncertainError as error:
            db.execute(
                update(Reply)
                .where(Reply.id == reply.id, Reply.status == "sending")
                .values(error_message=str(error))
            )
        except N8nDispatchError as error:
            db.execute(
                update(Reply)
                .where(Reply.id == reply.id, Reply.status == "sending")
                .values(status="failed", error_message=str(error))
            )
        db.commit()

    db.refresh(reply)
    return reply_response(reply, email.thread_id)


@router.get("/replies/{id}", response_model=ReplyResponse)
def get_reply(
    id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    row = db.execute(
        select(Reply, Email.thread_id)
        .join(Email, Reply.email_id == Email.id)
        .where(Reply.id == id, Reply.user_id == current_user.id, Email.user_id == current_user.id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Reply not found")
    reply, thread_id = row
    return reply_response(reply, thread_id)


@router.post(
    "/internal/webhooks/gmail-send-result",
    response_model=ReplyResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
def receive_gmail_send_result(
    payload: GmailSendResult,
    db: Annotated[Session, Depends(get_db)],
):
    row = db.execute(
        select(Reply, Email, Thread.gmail_thread_id)
        .join(Email, Reply.email_id == Email.id)
        .join(Thread, Email.thread_id == Thread.id)
        .where(
            Reply.id == payload.reply_id,
            Reply.user_id == payload.user_id,
            Reply.email_id == payload.email_id,
            Reply.idempotency_key == payload.idempotency_key,
            Email.user_id == payload.user_id,
            Thread.user_id == payload.user_id,
        )
        .with_for_update()
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Reply request not found")

    reply, email, expected_gmail_thread_id = row
    if reply.dispatch_id != payload.dispatch_id:
        raise HTTPException(status_code=409, detail="Stale Gmail dispatch result")
    if reply.status == "pending":
        raise HTTPException(status_code=409, detail="Reply request has not been dispatched")

    if payload.status == "failed":
        if reply.status != "sent":
            reply.status = "failed"
            reply.error_message = payload.error_message
            db.commit()
            db.refresh(reply)
        return reply_response(reply, email.thread_id)

    if payload.gmail_thread_id != expected_gmail_thread_id:
        raise HTTPException(status_code=409, detail="Gmail thread does not match reply request")
    if reply.status == "sent":
        if reply.gmail_message_id != payload.gmail_message_id:
            raise HTTPException(status_code=409, detail="Reply already completed with another Gmail ID")
        return reply_response(reply, email.thread_id)

    reply.status = "sent"
    reply.gmail_message_id = payload.gmail_message_id
    reply.sent_at = datetime.now(timezone.utc)
    reply.error_message = None
    email.status = "replied"
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="Gmail message already recorded") from error
    db.refresh(reply)
    return reply_response(reply, email.thread_id)
