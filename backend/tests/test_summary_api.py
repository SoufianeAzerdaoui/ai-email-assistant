"""Targeted integration tests for GET /summary."""

import os
import unittest
import warnings
from datetime import date, datetime, timedelta, timezone
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
from app.summary_routes import paris_day_bounds_utc


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class SummaryApiTests(unittest.TestCase):
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
            user=self.user, gmail_thread_id=f"summary-{uuid4()}", subject="Résumé"
        )
        self.other_thread = Thread(
            user=self.other_user, gmail_thread_id=f"summary-{uuid4()}", subject="Privé"
        )
        self.session.add_all([self.thread, self.other_thread])
        self.session.flush()

        day = datetime(2026, 6, 15, 8, tzinfo=timezone.utc)
        priorities = [1, 3, 2, 3, 1, 2, None]
        for index, priority in enumerate(priorities):
            self.session.add(self.make_email(
                user=self.user,
                thread=self.thread,
                received_at=day + timedelta(hours=index),
                status="pending",
                priority=priority,
                category="client" if index % 2 == 0 else "facture",
                expected_action=f"Traiter la demande {index + 1}",
            ))
        for index, status in enumerate(("replied", "draft_ready", "draft_ready", "ignored"), start=8):
            self.session.add(self.make_email(
                user=self.user,
                thread=self.thread,
                received_at=day + timedelta(hours=index),
                status=status,
                priority=2,
                category="autre",
            ))
        self.session.add(self.make_email(
            user=self.user,
            thread=self.thread,
            received_at=day - timedelta(days=1),
            status="pending",
            priority=3,
            category="client",
        ))
        self.session.add(self.make_email(
            user=self.other_user,
            thread=self.other_thread,
            received_at=day,
            status="pending",
            priority=3,
            category="client",
        ))
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

    def make_email(self, *, user, thread, received_at, status, priority, category, expected_action=None):
        return Email(
            user_id=user.id,
            thread_id=thread.id,
            gmail_message_id=f"summary-message-{uuid4()}",
            sender=f"sender-{uuid4()}@example.test",
            recipients=[user.email],
            subject=f"Message {uuid4()}",
            body_text="Contenu du message de test.",
            received_at=received_at,
            status=status,
            priority=priority,
            category=category,
            expected_action=expected_action,
        )

    def test_daily_counts_top_five_and_reasons(self):
        response = self.client.get("/summary?date=2026-06-15", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["date"], "2026-06-15")
        self.assertEqual(data["total_emails"], 11)
        self.assertEqual(data["pending_emails"], 7)
        self.assertEqual(data["replied_emails"], 1)
        self.assertEqual(data["draft_ready_emails"], 2)
        self.assertEqual(len(data["top_priority_emails"]), 5)
        self.assertEqual(
            [email["priority"] for email in data["top_priority_emails"]],
            [3, 3, 2, 2, 1],
        )
        for email in data["top_priority_emails"]:
            self.assertIn("Priorité", email["reason"])
            self.assertIn("catégorie", email["reason"])
            for sensitive in ("user_id", "gmail_message_id", "body_text"):
                self.assertNotIn(sensitive, email)
        self.assertIn("11 e-mails reçus", data["daily_summary"])
        self.assertIn("7 à traiter", data["daily_summary"])

    def test_empty_day(self):
        response = self.client.get("/summary?date=2030-01-01", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_emails"], 0)
        self.assertEqual(data["pending_emails"], 0)
        self.assertEqual(data["replied_emails"], 0)
        self.assertEqual(data["draft_ready_emails"], 0)
        self.assertEqual(data["top_priority_emails"], [])
        self.assertEqual(data["daily_summary"], "Aucun e-mail reçu le 01/01/2030.")

    def test_authentication_and_date_validation(self):
        self.assertEqual(self.client.get("/summary?date=2026-06-15").status_code, 401)
        self.assertEqual(self.client.get("/summary", headers=self.headers).status_code, 422)
        self.assertEqual(
            self.client.get("/summary?date=15-06-2026", headers=self.headers).status_code,
            422,
        )

    def test_paris_day_bounds_follow_winter_summer_and_dst_transitions(self):
        cases = (
            (
                date(2026, 1, 15),
                datetime(2026, 1, 14, 23, tzinfo=timezone.utc),
                datetime(2026, 1, 15, 23, tzinfo=timezone.utc),
                24,
            ),
            (
                date(2026, 6, 15),
                datetime(2026, 6, 14, 22, tzinfo=timezone.utc),
                datetime(2026, 6, 15, 22, tzinfo=timezone.utc),
                24,
            ),
            (
                date(2026, 3, 29),
                datetime(2026, 3, 28, 23, tzinfo=timezone.utc),
                datetime(2026, 3, 29, 22, tzinfo=timezone.utc),
                23,
            ),
            (
                date(2026, 10, 25),
                datetime(2026, 10, 24, 22, tzinfo=timezone.utc),
                datetime(2026, 10, 25, 23, tzinfo=timezone.utc),
                25,
            ),
        )

        for day, expected_start, expected_end, expected_hours in cases:
            with self.subTest(day=day):
                start, end = paris_day_bounds_utc(day)
                self.assertEqual(start, expected_start)
                self.assertEqual(end, expected_end)
                self.assertEqual((end - start).total_seconds(), expected_hours * 3600)

    def test_summary_uses_half_open_paris_day_bounds(self):
        day = date(2026, 3, 29)
        start, end = paris_day_bounds_utc(day)
        timestamps = (
            start - timedelta(microseconds=1),
            start,
            end - timedelta(microseconds=1),
            end,
        )
        for index, received_at in enumerate(timestamps):
            self.session.add(self.make_email(
                user=self.user,
                thread=self.thread,
                received_at=received_at,
                status="pending",
                priority=index % 3 + 1,
                category="client",
            ))
        self.session.commit()

        response = self.client.get("/summary?date=2026-03-29", headers=self.headers)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total_emails"], 2)
        self.assertEqual(data["pending_emails"], 2)
