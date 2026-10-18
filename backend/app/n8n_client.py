"""Small HTTP client for asynchronous n8n workflow dispatch."""

from datetime import datetime
from typing import TypedDict
from uuid import UUID

import httpx

from app.config import get_n8n_draft_settings


class ThreadMessage(TypedDict):
    email_id: str
    sender: str
    recipients: list[str]
    subject: str
    body: str
    received_at: str


class DraftGenerationDispatch(TypedDict):
    generation_id: str
    user_id: str
    email_id: str
    thread_id: str
    gmail_thread_id: str
    subject: str
    recipients: list[str]
    reply_to: list[str]
    tone: str
    messages: list[ThreadMessage]


class N8nDispatchError(Exception):
    """A sanitized dispatch failure safe to persist and return to clients."""


def dispatch_draft_generation(payload: DraftGenerationDispatch) -> None:
    try:
        settings = get_n8n_draft_settings()
        response = httpx.post(
            settings.webhook_url,
            json=payload,
            headers={"X-Webhook-Secret": settings.webhook_secret},
            timeout=settings.timeout_seconds,
        )
        response.raise_for_status()
    except RuntimeError as error:
        raise N8nDispatchError("n8n is not configured") from error
    except httpx.TimeoutException as error:
        raise N8nDispatchError("n8n request timed out") from error
    except httpx.HTTPStatusError as error:
        raise N8nDispatchError(f"n8n returned HTTP {error.response.status_code}") from error
    except httpx.RequestError as error:
        raise N8nDispatchError("n8n is unavailable") from error


def serialize_message(
    *, email_id: UUID, sender: str, recipients: list[str], subject: str,
    body: str, received_at: datetime,
) -> ThreadMessage:
    return {
        "email_id": str(email_id),
        "sender": sender,
        "recipients": recipients,
        "subject": subject,
        "body": body,
        "received_at": received_at.isoformat(),
    }
