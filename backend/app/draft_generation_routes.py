"""Asynchronous AI draft generation coordinated through n8n."""

from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.classification_routes import verify_webhook_secret
from app.database import get_db
from app.draft_generation_schemas import (
    DraftGenerationCreate,
    DraftGenerationResponse,
    DraftResult,
)
from app.draft_reply_routes import API_TO_DATABASE_TONE, DATABASE_TO_API_TONE, owned_email
from app.models import Draft, DraftGeneration, Email, Thread, User
from app.n8n_client import N8nDispatchError, dispatch_draft_generation, serialize_message


router = APIRouter(tags=["draft generations"])
ACTIVE_GENERATION_PREDICATE = text("status IN ('pending', 'generating')")


def generation_response(generation: DraftGeneration) -> DraftGenerationResponse:
    return DraftGenerationResponse(
        id=generation.id,
        email_id=generation.email_id,
        draft_id=generation.draft_id,
        tone=DATABASE_TO_API_TONE[generation.tone],
        status=generation.status,
        error_message=generation.error_message,
        created_at=generation.created_at,
        updated_at=generation.updated_at,
    )


def owned_generation(db: Session, user_id: UUID, generation_id: UUID) -> DraftGeneration:
    generation = db.scalar(
        select(DraftGeneration).where(
            DraftGeneration.id == generation_id,
            DraftGeneration.user_id == user_id,
        )
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Draft generation not found")
    return generation


@router.post(
    "/emails/{id}/draft/generate",
    response_model=DraftGenerationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def generate_draft(
    id: UUID,
    payload: DraftGenerationCreate,
    response: Response,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    email = owned_email(db, current_user.id, id)
    database_tone = API_TO_DATABASE_TONE[payload.tone]
    generation_id = uuid4()
    inserted_id = db.execute(
        insert(DraftGeneration)
        .values(
            id=generation_id,
            user_id=current_user.id,
            email_id=email.id,
            tone=database_tone,
            status="pending",
        )
        .on_conflict_do_nothing(
            index_elements=[
                DraftGeneration.user_id,
                DraftGeneration.email_id,
                DraftGeneration.tone,
            ],
            index_where=ACTIVE_GENERATION_PREDICATE,
        )
        .returning(DraftGeneration.id)
    ).scalar_one_or_none()

    if inserted_id is None:
        generation = db.scalar(
            select(DraftGeneration).where(
                DraftGeneration.user_id == current_user.id,
                DraftGeneration.email_id == email.id,
                DraftGeneration.tone == database_tone,
                DraftGeneration.status.in_(("pending", "generating")),
            )
        )
        if generation is None:
            db.rollback()
            raise HTTPException(status_code=409, detail="Unable to resolve active generation")
        response.status_code = status.HTTP_200_OK
        return generation_response(generation)

    db.commit()
    generation = db.get(DraftGeneration, generation_id)
    if generation is None:  # Defensive guard after the committed insert.
        raise HTTPException(status_code=409, detail="Draft generation was not persisted")

    thread = db.get(Thread, email.thread_id)
    messages = db.scalars(
        select(Email)
        .where(Email.thread_id == email.thread_id, Email.user_id == current_user.id)
        .order_by(Email.received_at.asc(), Email.id.asc())
    ).all()
    dispatch_payload = {
        "generation_id": str(generation.id),
        "user_id": str(current_user.id),
        "email_id": str(email.id),
        "thread_id": str(email.thread_id),
        "gmail_thread_id": thread.gmail_thread_id if thread else "",
        "subject": email.subject,
        "recipients": email.recipients,
        "reply_to": [email.sender],
        "tone": payload.tone,
        "messages": [
            serialize_message(
                email_id=message.id,
                sender=message.sender,
                recipients=message.recipients,
                subject=message.subject,
                body=message.body_text,
                received_at=message.received_at,
            )
            for message in messages
        ],
    }
    try:
        dispatch_draft_generation(dispatch_payload)
        db.execute(
            update(DraftGeneration)
            .where(
                DraftGeneration.id == generation.id,
                DraftGeneration.status == "pending",
            )
            .values(status="generating")
        )
    except N8nDispatchError as error:
        db.execute(
            update(DraftGeneration)
            .where(
                DraftGeneration.id == generation.id,
                DraftGeneration.status.in_(("pending", "generating")),
            )
            .values(status="failed", error_message=str(error))
        )
    db.commit()
    db.refresh(generation)
    return generation_response(generation)


@router.get("/draft-generations/{id}", response_model=DraftGenerationResponse)
def get_draft_generation(
    id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    return generation_response(owned_generation(db, current_user.id, id))


@router.post(
    "/internal/webhooks/draft-result",
    response_model=DraftGenerationResponse,
    dependencies=[Depends(verify_webhook_secret)],
)
def receive_draft_result(
    payload: DraftResult,
    db: Annotated[Session, Depends(get_db)],
):
    generation = db.scalar(
        select(DraftGeneration)
        .where(
            DraftGeneration.id == payload.generation_id,
            DraftGeneration.user_id == payload.user_id,
            DraftGeneration.email_id == payload.email_id,
        )
        .with_for_update()
    )
    if generation is None:
        raise HTTPException(status_code=404, detail="Draft generation not found")

    if generation.status == "ready":
        return generation_response(generation)
    if payload.status == "generating":
        if generation.status != "failed":
            generation.status = "generating"
            db.commit()
            db.refresh(generation)
        return generation_response(generation)
    if payload.status == "failed":
        generation.status = "failed"
        generation.error_message = payload.error_message
        db.commit()
        db.refresh(generation)
        return generation_response(generation)

    draft = Draft(
        email_id=generation.email_id,
        body_text=payload.body_text,
        tone=generation.tone,
        generated_by_ai=True,
    )
    db.add(draft)
    db.flush()
    generation.draft_id = draft.id
    generation.status = "ready"
    generation.error_message = None
    email = db.get(Email, generation.email_id)
    if email is not None:
        email.status = "draft_ready"
    db.commit()
    db.refresh(generation)
    return generation_response(generation)
