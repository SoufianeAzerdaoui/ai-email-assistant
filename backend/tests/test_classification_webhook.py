"""Targeted integration tests for the internal classification webhook."""

import os
import unittest
import warnings
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-32-characters")
os.environ.setdefault("WEBHOOK_SECRET", "classification-test-secret-at-least-32-chars")
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.config import get_webhook_secret
from app.database import get_db
from app.main import app
from app.models import Email, Thread, User


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class ClassificationWebhookTests(unittest.TestCase):
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
        self.session.flush()
        self.thread = Thread(
            user_id=self.user.id,
            gmail_thread_id=f"classification-{uuid4()}",
            subject="Demande de devis",
        )
        self.session.add(self.thread)
        self.session.flush()
        self.email = Email(
            user_id=self.user.id,
            thread_id=self.thread.id,
            gmail_message_id=f"classification-message-{uuid4()}",
            sender="client@example.test",
            recipients=[self.user.email],
            subject="Demande de devis",
            body_text="Bonjour, pouvez-vous préparer un devis ?",
            received_at=datetime.now(timezone.utc),
        )
        self.session.add(self.email)
        self.session.commit()

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.headers = {"X-Webhook-Secret": os.environ["WEBHOOK_SECRET"]}
        self.payload = {
            "user_id": str(self.user.id),
            "email_id": str(self.email.id),
            "category": "client",
            "priority": 3,
            "summary": "Le client demande un devis pour son projet.",
            "expected_action": "Préparer et envoyer le devis demandé.",
            "needs_review": False,
        }

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def test_updates_existing_email(self):
        response = self.client.post(
            "/internal/webhooks/classification",
            headers=self.headers,
            json=self.payload,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "email_id": str(self.email.id),
            "category": "client",
            "priority": 3,
            "summary": "Le client demande un devis pour son projet.",
            "expected_action": "Préparer et envoyer le devis demandé.",
            "needs_review": False,
        })
        self.session.refresh(self.email)
        self.assertEqual(self.email.category, "client")
        self.assertEqual(self.email.priority, 3)
        self.assertEqual(self.email.summary, self.payload["summary"])
        self.assertEqual(self.email.expected_action, self.payload["expected_action"])

    def test_requires_valid_shared_secret(self):
        missing = self.client.post("/internal/webhooks/classification", json=self.payload)
        invalid = self.client.post(
            "/internal/webhooks/classification",
            headers={"X-Webhook-Secret": "wrong-secret"},
            json=self.payload,
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn(os.environ["WEBHOOK_SECRET"], missing.text)
        self.assertNotIn(os.environ["WEBHOOK_SECRET"], invalid.text)
        self.session.refresh(self.email)
        self.assertIsNone(self.email.category)

    def test_email_is_scoped_to_user(self):
        payload = {**self.payload, "user_id": str(self.other_user.id)}
        mismatch = self.client.post(
            "/internal/webhooks/classification", headers=self.headers, json=payload
        )
        missing = self.client.post(
            "/internal/webhooks/classification",
            headers=self.headers,
            json={**self.payload, "email_id": str(uuid4())},
        )

        self.assertEqual(mismatch.status_code, 404)
        self.assertEqual(missing.status_code, 404)
        self.session.refresh(self.email)
        self.assertIsNone(self.email.category)

    def test_rejects_invalid_classification_values(self):
        invalid_payloads = (
            {**self.payload, "category": "urgent"},
            {**self.payload, "priority": 0},
            {**self.payload, "priority": 4},
            {**self.payload, "summary": "   "},
            {**self.payload, "expected_action": "\n"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.post(
                    "/internal/webhooks/classification", headers=self.headers, json=payload
                )
                self.assertEqual(response.status_code, 422)

        self.session.refresh(self.email)
        self.assertIsNone(self.email.category)
