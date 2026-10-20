"""Integration tests for the internal Gmail message ingestion webhook."""

import os
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-32-characters")
os.environ.setdefault("WEBHOOK_SECRET", "gmail-import-test-secret-at-least-32-chars")
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.config import get_webhook_secret
from app.database import get_db
from app.gmail_import_routes import import_gmail_messages
from app.gmail_import_schemas import GmailImportRequest
from app.main import app
from app.models import Email, Thread, User


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class GmailImportWebhookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_webhook_secret.cache_clear()
        cls.engine = create_engine(os.environ["TEST_DATABASE_URL"])

    @classmethod
    def tearDownClass(cls):
        get_webhook_secret.cache_clear()
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(self.connection, join_transaction_mode="create_savepoint")
        self.user = User(email=f"{uuid4()}@example.test", password_hash="test-hash")
        self.other_user = User(email=f"{uuid4()}@example.test", password_hash="test-hash")
        self.session.add_all([self.user, self.other_user])
        self.session.commit()

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.headers = {"X-Webhook-Secret": os.environ["WEBHOOK_SECRET"]}
        self.thread_gmail_id = f"gmail-thread-{uuid4()}"
        self.payload = {
            "user_id": str(self.user.id),
            "messages": [
                self.message("gmail-message-1", "Premier message", "2026-10-17T08:30:00+02:00"),
                self.message("gmail-message-2", "Re: Premier message", "2026-10-17T09:45:00+02:00"),
            ],
        }

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def message(self, gmail_message_id, subject, received_at):
        return {
            "gmail_message_id": gmail_message_id,
            "gmail_thread_id": self.thread_gmail_id,
            "message_id": f"<{gmail_message_id}@mail.example>",
            "sender": "Cliente Exemple <cliente@example.test>",
            "recipients": [self.user.email, "archive@example.test"],
            "subject": subject,
            "body_text": f"Contenu de {subject}",
            "received_at": received_at,
        }

    def post(self, payload=None, headers=None):
        return self.client.post(
            "/internal/webhooks/gmail/messages",
            headers=self.headers if headers is None else headers,
            json=self.payload if payload is None else payload,
        )

    def test_imports_messages_and_preserves_thread_and_fields(self):
        response = self.post()

        self.assertEqual(response.status_code, 200)
        data = response.json()
        tasks = data.pop("classification_tasks")
        self.assertEqual(data, {
            "user_id": str(self.user.id),
            "received_count": 2,
            "imported_count": 2,
            "duplicate_count": 0,
            "repaired_count": 0,
            "created_thread_count": 1,
        })
        thread = self.session.scalar(select(Thread).where(
            Thread.user_id == self.user.id,
            Thread.gmail_thread_id == self.thread_gmail_id,
        ))
        emails = self.session.scalars(
            select(Email).where(Email.user_id == self.user.id).order_by(Email.received_at)
        ).all()
        self.assertIsNotNone(thread)
        self.assertEqual(thread.subject, "Premier message")
        self.assertEqual([email.thread_id for email in emails], [thread.id, thread.id])
        self.assertEqual([email.gmail_message_id for email in emails], [
            "gmail-message-1", "gmail-message-2",
        ])
        self.assertEqual(emails[0].message_id, "<gmail-message-1@mail.example>")
        self.assertEqual(emails[0].sender, "Cliente Exemple <cliente@example.test>")
        self.assertEqual(emails[0].recipients, [self.user.email, "archive@example.test"])
        self.assertEqual(emails[0].body_text, "Contenu de Premier message")
        self.assertEqual(emails[0].received_at, datetime(2026, 10, 17, 6, 30, tzinfo=timezone.utc))
        self.assertEqual([task["email_id"] for task in tasks], [str(email.id) for email in emails])
        self.assertEqual([task["user_id"] for task in tasks], [str(self.user.id)] * 2)
        self.assertEqual([task["subject"] for task in tasks], [
            "Premier message", "Re: Premier message",
        ])
        self.assertEqual([task["body"] for task in tasks], [email.body_text for email in emails])

    def test_reimport_of_unclassified_messages_recovers_classification_tasks(self):
        first = self.post()
        second = self.post()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["imported_count"], 0)
        self.assertEqual(second.json()["duplicate_count"], 2)
        self.assertEqual(second.json()["repaired_count"], 0)
        self.assertEqual(second.json()["created_thread_count"], 0)
        self.assertEqual(
            [task["email_id"] for task in second.json()["classification_tasks"]],
            [task["email_id"] for task in first.json()["classification_tasks"]],
        )
        self.assertEqual(self.session.scalar(
            select(func.count()).select_from(Email).where(Email.user_id == self.user.id)
        ), 2)
        self.assertEqual(self.session.scalar(
            select(func.count()).select_from(Thread).where(Thread.user_id == self.user.id)
        ), 1)

    def test_reimport_of_classified_message_does_not_redispatch_or_overwrite(self):
        message = self.payload["messages"][0]
        first = self.post({**self.payload, "messages": [message]})
        email_id = first.json()["classification_tasks"][0]["email_id"]
        email = self.session.get(Email, email_id)
        expected = {
            "category": "facture",
            "priority": 3,
            "summary": "Facture à régler.",
            "expected_action": "Vérifier puis régler la facture.",
            "needs_review": True,
        }
        for field, value in expected.items():
            setattr(email, field, value)
        self.session.commit()

        response = self.post({
            **self.payload,
            "messages": [{
                **message,
                "subject": "Objet différent reçu pendant le retry",
                "body_text": "Contenu différent reçu pendant le retry",
            }],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["imported_count"], 0)
        self.assertEqual(response.json()["classification_tasks"], [])
        self.session.refresh(email)
        self.assertEqual(
            {field: getattr(email, field) for field in expected},
            expected,
        )

    def test_partial_classification_is_treated_as_already_in_progress(self):
        message = self.payload["messages"][0]
        first = self.post({**self.payload, "messages": [message]})
        email = self.session.get(Email, first.json()["classification_tasks"][0]["email_id"])
        email.category = "client"
        self.session.commit()

        response = self.post({**self.payload, "messages": [message]})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["classification_tasks"], [])
        self.session.refresh(email)
        self.assertEqual(email.category, "client")
        self.assertIsNone(email.priority)

    def test_reimport_of_ten_unclassified_messages_recovers_the_whole_batch(self):
        messages = [
            self.message(
                f"gmail-batch-message-{index}",
                f"Message du lot {index}",
                f"2026-10-17T{index:02d}:30:00+02:00",
            )
            for index in range(10)
        ]
        payload = {**self.payload, "messages": messages}

        first = self.post(payload)
        second = self.post(payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["imported_count"], 10)
        self.assertEqual(len(first.json()["classification_tasks"]), 10)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["imported_count"], 0)
        self.assertEqual(second.json()["duplicate_count"], 10)
        self.assertEqual(len(second.json()["classification_tasks"]), 10)
        self.assertEqual(self.session.scalar(
            select(func.count()).select_from(Email).where(Email.user_id == self.user.id)
        ), 10)

    def test_lost_response_followed_by_retry_recovers_same_task(self):
        message = self.payload["messages"][0]
        first_response = self.post({**self.payload, "messages": [message]})
        first_task = first_response.json()["classification_tasks"][0]

        retry_response = self.post({**self.payload, "messages": [message]})

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(retry_response.json()["imported_count"], 0)
        self.assertEqual(retry_response.json()["duplicate_count"], 1)
        self.assertEqual(retry_response.json()["classification_tasks"], [first_task])

    def test_prefers_plain_text_over_html(self):
        message = {
            **self.payload["messages"][0],
            "body_text": "Version texte lisible.",
            "body_html": "<p>Version <strong>HTML</strong>.</p>",
        }
        response = self.post({**self.payload, "messages": [message]})

        self.assertEqual(response.status_code, 200)
        email = self.session.scalar(select(Email).where(
            Email.user_id == self.user.id,
            Email.gmail_message_id == message["gmail_message_id"],
        ))
        self.assertEqual(email.body_text, "Version texte lisible.")

    def test_repairs_exact_previous_html_without_overwriting_human_text(self):
        raw_html = (
            "<!doctype html><html><head><style>.hidden{display:none}</style></head>"
            "<body><p>Bonjour&nbsp;Alice,</p><p>Consultez "
            "<a href=\"https://example.test/facture\">votre facture</a>.</p></body></html>"
        )
        first_message = {**self.payload["messages"][0], "body_text": raw_html}
        second_message = {**self.payload["messages"][1], "body_text": "Texte corrigé manuellement"}
        self.assertEqual(self.post({
            **self.payload, "messages": [first_message, second_message]
        }).status_code, 200)

        repaired_payload = {
            **self.payload,
            "messages": [
                {**first_message, "body_text": "", "body_html": raw_html},
                {**second_message, "body_text": "", "body_html": raw_html},
            ],
        }
        response = self.post(repaired_payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["imported_count"], 0)
        self.assertEqual(response.json()["duplicate_count"], 2)
        self.assertEqual(response.json()["repaired_count"], 1)
        emails = {
            email.gmail_message_id: email.body_text
            for email in self.session.scalars(select(Email).where(Email.user_id == self.user.id))
        }
        self.assertEqual(
            emails["gmail-message-1"],
            "Bonjour Alice,\n\nConsultez votre facture (https://example.test/facture).",
        )
        self.assertEqual(emails["gmail-message-2"], "Texte corrigé manuellement")

    def test_repairs_previous_converted_tracking_output(self):
        tracking_url = "https://www.helloasso.com/click?redirect=" + ("x" * 180)
        raw_html = f'<p><a href="{tracking_url}">Voir mon inscription</a></p>'
        previous_output = f"Voir mon inscription ({tracking_url})"
        message = {
            **self.payload["messages"][0],
            "body_text": previous_output,
        }
        self.assertEqual(self.post({**self.payload, "messages": [message]}).status_code, 200)

        response = self.post({
            **self.payload,
            "messages": [{**message, "body_text": "", "body_html": raw_html}],
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["repaired_count"], 1)
        email = self.session.scalar(select(Email).where(
            Email.user_id == self.user.id,
            Email.gmail_message_id == message["gmail_message_id"],
        ))
        self.assertEqual(email.body_text, "Voir mon inscription")

    def test_same_gmail_ids_are_scoped_to_user(self):
        self.assertEqual(self.post().status_code, 200)
        other_payload = {**self.payload, "user_id": str(self.other_user.id)}
        response = self.post(other_payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["imported_count"], 2)
        self.assertEqual(self.session.scalar(
            select(func.count()).select_from(Email).where(
                Email.gmail_message_id == "gmail-message-1"
            )
        ), 2)

        original_tasks = self.post().json()["classification_tasks"]
        other_tasks = self.post(other_payload).json()["classification_tasks"]
        self.assertTrue(all(task["user_id"] == str(self.user.id) for task in original_tasks))
        self.assertTrue(all(task["user_id"] == str(self.other_user.id) for task in other_tasks))

    def test_requires_secret_and_existing_user(self):
        self.assertEqual(self.post(headers={}).status_code, 401)
        self.assertEqual(self.post(headers={"X-Webhook-Secret": "wrong"}).status_code, 401)
        unknown = self.post({**self.payload, "user_id": str(uuid4())})
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(self.session.scalar(
            select(func.count()).select_from(Email).where(Email.user_id == self.user.id)
        ), 0)

    def test_rejects_invalid_or_sensitive_payload_fields(self):
        invalid_payloads = (
            {**self.payload, "messages": [{**self.payload["messages"][0], "received_at": "2026-10-17T08:30:00"}]},
            {**self.payload, "messages": [self.payload["messages"][0], self.payload["messages"][0]]},
            {**self.payload, "messages": [{**self.payload["messages"][0], "access_token": "must-not-be-stored"}]},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload).status_code, 422)
        self.assertEqual(self.session.scalar(
            select(func.count()).select_from(Email).where(Email.user_id == self.user.id)
        ), 0)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class GmailImportConcurrencyTests(unittest.TestCase):
    def test_concurrent_imports_create_one_email_and_one_thread(self):
        engine = create_engine(os.environ["TEST_DATABASE_URL"])
        unique = uuid4()
        with Session(engine) as db:
            user = User(email=f"{unique}@example.test", password_hash="test-hash")
            db.add(user)
            db.commit()
            user_id = user.id

        payload = {
            "user_id": str(user_id),
            "messages": [{
                "gmail_message_id": f"concurrent-message-{unique}",
                "gmail_thread_id": f"concurrent-thread-{unique}",
                "message_id": f"<concurrent-{unique}@example.test>",
                "sender": "sender@example.test",
                "recipients": ["recipient@example.test"],
                "subject": "Import concurrent",
                "body_text": "Un seul message doit être enregistré.",
                "received_at": "2026-10-19T10:00:00+02:00",
            }],
        }

        def run_import(_):
            with Session(engine) as db:
                return import_gmail_messages(GmailImportRequest.model_validate(payload), db)

        try:
            with ThreadPoolExecutor(max_workers=8) as executor:
                responses = list(executor.map(run_import, range(8)))

            self.assertEqual(sum(response.imported_count for response in responses), 1)
            with Session(engine) as db:
                self.assertEqual(db.scalar(
                    select(func.count()).select_from(Email).where(Email.user_id == user_id)
                ), 1)
                self.assertEqual(db.scalar(
                    select(func.count()).select_from(Thread).where(Thread.user_id == user_id)
                ), 1)
        finally:
            with Session(engine) as db:
                db.execute(delete(Email).where(Email.user_id == user_id))
                db.execute(delete(Thread).where(Thread.user_id == user_id))
                db.execute(delete(User).where(User.id == user_id))
                db.commit()
            engine.dispose()
