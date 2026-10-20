"""Prepare and inspect the isolated Gmail batch HTTP integration database."""

from __future__ import annotations

import argparse
import json
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.database import get_database_url, get_engine
from app.models import Email, SyncExecution, SyncState, Thread, User


DATABASE_NAME = "mailflow_gmail_batch_test"
DATABASE_PORT = 55432
FIXTURE_USER_ID = UUID("00000000-0000-4000-8000-000000000001")
FIXTURE_EMAIL = "gmail-batch-fixture@example.test"


def assert_isolated_database() -> None:
    url = make_url(str(get_database_url()))
    if url.database != DATABASE_NAME or url.port != DATABASE_PORT:
        raise RuntimeError(
            f"Refusing database {url.database!r} on port {url.port!r}; "
            f"expected {DATABASE_NAME!r} on port {DATABASE_PORT}."
        )


def prepare_database() -> None:
    assert_isolated_database()
    with Session(get_engine()) as db:
        db.execute(text(
            "TRUNCATE TABLE workflow_errors, replies, draft_generations, drafts, "
            "emails, threads, sync_states, sync_executions, users CASCADE"
        ))
        db.add(User(
            id=FIXTURE_USER_ID,
            email=FIXTURE_EMAIL,
            password_hash="integration-test-only-no-login",
            is_admin=False,
        ))
        db.commit()
    print(json.dumps({
        "database": DATABASE_NAME,
        "port": DATABASE_PORT,
        "user_id": str(FIXTURE_USER_ID),
        "reset": True,
    }))


def inspect_database() -> None:
    assert_isolated_database()
    with Session(get_engine()) as db:
        state = db.get(SyncState, FIXTURE_USER_ID)
        executions = db.scalars(
            select(SyncExecution)
            .where(SyncExecution.user_id == FIXTURE_USER_ID)
            .order_by(SyncExecution.started_at)
        ).all()
        email_count = db.scalar(
            select(func.count()).select_from(Email).where(Email.user_id == FIXTURE_USER_ID)
        )
        unique_gmail_count = db.scalar(
            select(func.count(func.distinct(Email.gmail_message_id))).where(
                Email.user_id == FIXTURE_USER_ID
            )
        )
        unclassified_count = db.scalar(
            select(func.count()).select_from(Email).where(
                Email.user_id == FIXTURE_USER_ID,
                Email.category.is_(None),
                Email.priority.is_(None),
                Email.summary.is_(None),
                Email.expected_action.is_(None),
            )
        )
        thread_count = db.scalar(
            select(func.count()).select_from(Thread).where(Thread.user_id == FIXTURE_USER_ID)
        )

    print(json.dumps({
        "user_id": str(FIXTURE_USER_ID),
        "emails": email_count,
        "unique_gmail_messages": unique_gmail_count,
        "threads": thread_count,
        "unclassified_emails": unclassified_count,
        "cursor": state.cursor if state else None,
        "sync_executions": [
            {
                "status": execution.status,
                "cursor_before": execution.cursor_before,
                "cursor_after": execution.cursor_after,
                "imported_count": execution.imported_count,
            }
            for execution in executions
        ],
    }, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "inspect"))
    args = parser.parse_args()
    if args.command == "prepare":
        prepare_database()
    else:
        inspect_database()


if __name__ == "__main__":
    main()
