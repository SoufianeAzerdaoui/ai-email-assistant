"""Integration tests for authenticated email REST endpoints."""

import os
import unittest
import warnings
from datetime import datetime, timedelta, timezone
from uuid import uuid4

os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-32-characters")
os.environ.setdefault("JWT_EXPIRE_MINUTES", "60")
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth import create_access_token
from app.database import get_db
from app.main import app
from app.models import Email, Thread, User


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class EmailApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(os.environ["TEST_DATABASE_URL"])

    @classmethod
    def tearDownClass(cls):
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
            user=self.user, gmail_thread_id=f"thread-{uuid4()}", subject="Project Alpha"
        )
        self.second_thread = Thread(
            user=self.user, gmail_thread_id=f"thread-{uuid4()}", subject="Invoices"
        )
        self.other_thread = Thread(
            user=self.other_user, gmail_thread_id=f"thread-{uuid4()}", subject="Private"
        )
        self.session.add_all([self.thread, self.second_thread, self.other_thread])
        self.session.flush()

        base = datetime(2026, 1, 10, 9, tzinfo=timezone.utc)
        self.emails = [
            self.make_email(
                self.thread, 1, base, "alice@example.com", "Alpha kickoff",
                "The project starts today", "client", 2, "pending",
            ),
            self.make_email(
                self.thread, 2, base + timedelta(hours=2), "bob@example.com", "Re: Alpha kickoff",
                "Here is the urgent project update", "client", 3, "draft_ready",
            ),
            self.make_email(
                self.second_thread, 3, base + timedelta(days=1), "billing@example.com", "January invoice",
                "Invoice attached", "facture", 3, "pending",
            ),
            self.make_email(
                self.second_thread, 4, base + timedelta(days=2), "news@example.com", "Weekly digest",
                "Product news", "newsletter", 1, "ignored",
            ),
            self.make_email(
                self.second_thread, 5, base + timedelta(days=3), "alice@example.com", "Follow up",
                "A final client note", "client", 2, "replied",
            ),
        ]
        self.other_email = self.make_email(
            self.other_thread, 99, base + timedelta(days=10), "private@example.com", "Secret",
            "Other user's content", "autre", 1, "pending", user=self.other_user,
        )
        self.session.add_all([*self.emails, self.other_email])
        self.session.commit()

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user)}"}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def make_email(
        self, thread, number, received_at, sender, subject, body, category, priority, status,
        *, user=None,
    ):
        owner = user or self.user
        return Email(
            user_id=owner.id,
            thread_id=thread.id,
            gmail_message_id=f"message-{uuid4()}-{number}",
            sender=sender,
            recipients=[owner.email],
            subject=subject,
            body_text=body,
            received_at=received_at,
            category=category,
            priority=priority,
            status=status,
        )

    def test_list_pagination_total_and_descending_sort(self):
        first = self.client.get("/emails?page=1&limit=2", headers=self.headers)
        second = self.client.get("/emails?page=2&limit=2", headers=self.headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["total"], 5)
        self.assertEqual(first.json()["page"], 1)
        self.assertEqual(first.json()["limit"], 2)
        self.assertEqual(
            [item["id"] for item in first.json()["items"]],
            [str(self.emails[4].id), str(self.emails[3].id)],
        )
        self.assertEqual(
            [item["id"] for item in second.json()["items"]],
            [str(self.emails[2].id), str(self.emails[1].id)],
        )

    def test_combined_filters_period_and_search(self):
        response = self.client.get(
            "/emails",
            params={
                "category": "client",
                "priority": 3,
                "status": "draft_ready",
                "sender": "BOB@EXAMPLE",
                "date_from": "2026-01-10T10:00:00Z",
                "date_to": "2026-01-10T12:00:00Z",
                "search": "urgent project",
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["items"][0]["id"], str(self.emails[1].id))

        body_search = self.client.get(
            "/emails", params={"search": "final client"}, headers=self.headers
        )
        self.assertEqual(body_search.json()["total"], 1)
        self.assertEqual(body_search.json()["items"][0]["id"], str(self.emails[4].id))

    def test_email_detail_excludes_internal_and_sensitive_fields(self):
        response = self.client.get(f"/emails/{self.emails[0].id}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["subject"], "Alpha kickoff")
        for field in ("user_id", "gmail_message_id", "message_id", "password_hash", "token_version"):
            self.assertNotIn(field, data)

    def test_thread_returns_complete_chronological_conversation(self):
        response = self.client.get(f"/threads/{self.thread.id}", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["subject"], "Project Alpha")
        self.assertEqual(
            [email["id"] for email in response.json()["emails"]],
            [str(self.emails[0].id), str(self.emails[1].id)],
        )

    def test_security_and_not_found_do_not_reveal_other_users(self):
        for path in ("/emails", f"/emails/{self.emails[0].id}", f"/threads/{self.thread.id}"):
            self.assertEqual(self.client.get(path).status_code, 401)

        self.assertEqual(
            self.client.get(f"/emails/{self.other_email.id}", headers=self.headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/threads/{self.other_thread.id}", headers=self.headers).status_code,
            404,
        )
        listed_ids = {
            item["id"] for item in self.client.get("/emails", headers=self.headers).json()["items"]
        }
        self.assertNotIn(str(self.other_email.id), listed_ids)

    def test_invalid_parameters_return_422(self):
        invalid_queries = (
            {"page": 0},
            {"limit": 101},
            {"priority": 4},
            {"category": "unknown"},
            {"status": "unknown"},
            {"date_from": "2026-01-11T00:00:00Z", "date_to": "2026-01-10T00:00:00Z"},
        )
        for params in invalid_queries:
            with self.subTest(params=params):
                response = self.client.get("/emails", params=params, headers=self.headers)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/emails/not-a-uuid", headers=self.headers).status_code, 422)
