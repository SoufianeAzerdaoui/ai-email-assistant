"""Integration checks against a migrated, disposable PostgreSQL database."""

import os
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Draft, Email, Reply, SyncExecution, SyncState, Thread, User, WorkflowError


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class DatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(os.environ["TEST_DATABASE_URL"])

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(self.connection)
        self.addCleanup(self.connection.close)
        self.addCleanup(self.transaction.rollback)
        self.addCleanup(self.session.close)
        self.user = User(email=f"{uuid4()}@example.test", password_hash="test-hash")
        self.session.add(self.user)
        self.session.flush()
        self.thread = Thread(user=self.user, gmail_thread_id="thread-1")
        self.session.add(self.thread)
        self.session.flush()
        self.email = self.make_email()
        self.session.add(self.email)
        self.session.flush()

    def make_email(self, **changes):
        values = dict(
            user_id=self.user.id, thread_id=self.thread.id,
            gmail_message_id="message-1", sender="sender@example.test",
            recipients=[self.user.email], received_at=datetime.now(timezone.utc),
        )
        return Email(**(values | changes))

    def reject(self, record, constraint):
        with self.assertRaises(IntegrityError) as raised:
            with self.session.begin_nested():
                self.session.add(record)
                self.session.flush()
        self.assertEqual(raised.exception.orig.diag.constraint_name, constraint)

    def test_gmail_uniqueness(self):
        self.reject(self.make_email(), "uq_emails_user_gmail")
        self.reject(
            Thread(user_id=self.user.id, gmail_thread_id="thread-1"),
            "uq_threads_user_gmail",
        )

    def test_reply_idempotency_across_emails(self):
        other = self.make_email(gmail_message_id="message-2")
        self.session.add(other)
        self.session.flush()
        self.session.add(Reply(
            user_id=self.user.id, email_id=self.email.id,
            idempotency_key="send-1", body_text="Hello",
        ))
        self.session.flush()
        self.reject(Reply(
            user_id=self.user.id, email_id=other.id,
            idempotency_key="send-1", body_text="Retry",
        ), "uq_replies_user_idempotency")
        self.reject(Reply(
            user_id=self.user.id, email_id=self.email.id,
            idempotency_key=" ", body_text="Hello",
        ), "ck_replies_idempotency_key")

    def test_sent_gmail_uniqueness_and_nullable_unsent_ids(self):
        for key, gmail_id in [("a", None), ("b", None), ("c", "sent-1")]:
            self.session.add(Reply(
                user_id=self.user.id, email_id=self.email.id, idempotency_key=key,
                body_text="Hello", gmail_message_id=gmail_id,
            ))
        self.session.flush()
        self.reject(Reply(
            user_id=self.user.id, email_id=self.email.id, idempotency_key="d",
            body_text="Hello", gmail_message_id="sent-1",
        ), "uq_replies_user_gmail")

    def test_ownership_and_account_scoped_gmail_ids(self):
        other = User(email=f"{uuid4()}@example.test", password_hash="test-hash")
        self.session.add(other)
        self.session.flush()
        thread = Thread(user_id=other.id, gmail_thread_id="thread-1")
        self.session.add(thread)
        self.session.flush()
        self.session.add(self.make_email(user_id=other.id, thread_id=thread.id))
        self.session.flush()
        self.reject(
            self.make_email(user_id=other.id, gmail_message_id="different"),
            "fk_emails_thread_user",
        )
        self.reject(Reply(
            user_id=other.id, email_id=self.email.id,
            idempotency_key="send-1", body_text="Hello",
        ), "fk_replies_email_user")

    def test_reply_draft_must_belong_to_same_email(self):
        draft = Draft(email=self.email, body_text="Draft")
        other = self.make_email(gmail_message_id="message-2")
        self.session.add_all([draft, other])
        self.session.flush()
        self.reject(Reply(
            user_id=self.user.id, email_id=other.id, draft_id=draft.id,
            idempotency_key="send-1", body_text="Hello",
        ), "fk_replies_draft_email")

    def test_sync_state_and_error_idempotency(self):
        execution = SyncExecution(user=self.user, idempotency_key="sync-1")
        self.session.add(execution)
        self.session.flush()
        self.reject(
            SyncExecution(user_id=self.user.id, idempotency_key="sync-1"),
            "uq_sync_executions_user_key",
        )
        self.session.add(SyncState(user_id=self.user.id, cursor="123"))
        self.session.flush()
        self.reject(SyncState(user_id=self.user.id), "pk_sync_states")
        values = dict(
            user_id=self.user.id, sync_execution_id=execution.id,
            idempotency_key="error-1", workflow_name="sync", message="Test failure",
        )
        self.session.add(WorkflowError(**values))
        self.session.flush()
        self.reject(WorkflowError(**values), "uq_workflow_errors_user_key")

    def test_foreign_keys_and_classification_constraints(self):
        self.reject(
            self.make_email(thread_id=uuid4(), gmail_message_id="orphan"),
            "fk_emails_thread_user",
        )
        self.reject(self.make_email(priority=4, gmail_message_id="bad-priority"), "ck_emails_priority")
        self.reject(
            self.make_email(category="unknown", gmail_message_id="bad-category"),
            "ck_emails_category",
        )

    def test_relationship_roundtrip(self):
        draft = Draft(email=self.email, body_text="Draft")
        execution = SyncExecution(user=self.user, idempotency_key="sync-1", status="succeeded")
        self.session.add_all([draft, execution])
        self.session.flush()
        reply = Reply(user=self.user, email=self.email, draft=draft,
                      idempotency_key="send-1", body_text="Hello")
        state = SyncState(user=self.user, last_successful_execution=execution, cursor="123")
        error = WorkflowError(user=self.user, sync_execution=execution,
                              idempotency_key="error-1", workflow_name="sync", message="Test")
        self.session.add_all([reply, state, error])
        self.session.flush()
        self.session.expire_all()
        self.assertEqual(self.user.threads, [self.thread])
        self.assertEqual(self.thread.emails, [self.email])
        self.assertEqual(self.email.drafts, [draft])
        self.assertEqual(self.email.replies, [reply])
        self.assertEqual(reply.draft, draft)
        self.assertEqual(self.user.sync_state.last_successful_execution, execution)
        self.assertEqual(execution.workflow_errors, [error])
