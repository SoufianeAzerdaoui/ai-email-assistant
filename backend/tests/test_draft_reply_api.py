"""Targeted integration tests for drafts and idempotent reply requests."""

import os
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-32-characters")
os.environ.setdefault("JWT_EXPIRE_MINUTES", "60")
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.auth import create_access_token
from app.database import get_db, get_engine
from app.main import app
from app.models import Draft, Email, Reply, Thread, User


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class DraftReplyApiTests(unittest.TestCase):
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
        self.thread = Thread(user=self.user, gmail_thread_id=f"thread-{uuid4()}")
        self.other_thread = Thread(user=self.other_user, gmail_thread_id=f"thread-{uuid4()}")
        self.session.add_all([self.thread, self.other_thread])
        self.session.flush()
        self.email = self.make_email(self.user, self.thread)
        self.other_email = self.make_email(self.other_user, self.other_thread)
        self.session.add_all([self.email, self.other_email])
        self.session.commit()

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user)}"}
        self.other_headers = {"Authorization": f"Bearer {create_access_token(self.other_user)}"}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    @staticmethod
    def make_email(user, thread):
        return Email(
            user_id=user.id,
            thread_id=thread.id,
            gmail_message_id=f"message-{uuid4()}",
            sender="client@example.test",
            recipients=[user.email],
            subject="Demande client",
            body_text="Pouvez-vous me répondre ?",
            received_at=datetime.now(timezone.utc),
            status="pending",
            category="client",
            priority=3,
        )

    def create_draft(self):
        return self.client.post(
            f"/emails/{self.email.id}/draft",
            json={"body_text": "Bonjour, voici ma réponse.", "tone": "formel"},
            headers=self.headers,
        )

    def test_create_get_and_update_manual_draft(self):
        created = self.create_draft()
        self.assertEqual(created.status_code, 201)
        data = created.json()
        self.assertEqual(data["body_text"], "Bonjour, voici ma réponse.")
        self.assertEqual(data["tone"], "formel")
        self.assertFalse(data["generated_by_ai"])
        self.assertEqual(self.session.get(Email, self.email.id).status, "draft_ready")

        fetched = self.client.get(f"/drafts/{data['id']}", headers=self.headers)
        self.assertEqual(fetched.status_code, 200)
        updated = self.client.put(
            f"/drafts/{data['id']}",
            json={"body_text": "Merci, la demande est prise en compte.", "tone": "court"},
            headers=self.headers,
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["tone"], "court")
        self.assertEqual(updated.json()["body_text"], "Merci, la demande est prise en compte.")

    def test_draft_validation_authentication_and_isolation(self):
        self.assertEqual(self.client.post(
            f"/emails/{self.email.id}/draft",
            json={"body_text": " ", "tone": "neutre"},
            headers=self.headers,
        ).status_code, 422)
        self.assertEqual(self.client.post(
            f"/emails/{self.email.id}/draft",
            json={"body_text": "Réponse", "tone": "amical"},
            headers=self.headers,
        ).status_code, 422)
        self.assertEqual(self.client.post(
            f"/emails/{self.email.id}/draft",
            json={"body_text": "Réponse", "tone": "neutre"},
        ).status_code, 401)
        self.assertEqual(self.client.post(
            f"/emails/{self.email.id}/draft",
            json={"body_text": "Réponse", "tone": "neutre"},
            headers=self.other_headers,
        ).status_code, 404)

        draft_id = self.create_draft().json()["id"]
        self.assertEqual(
            self.client.get(f"/drafts/{draft_id}", headers=self.other_headers).status_code,
            404,
        )
        self.assertEqual(self.client.put(
            f"/drafts/{draft_id}", json={}, headers=self.headers
        ).status_code, 422)

    def test_confirmed_reply_is_pending_and_idempotent(self):
        draft_id = self.create_draft().json()["id"]
        payload = {
            "confirmed": True,
            "idempotency_key": "reply-request-1",
            "draft_id": draft_id,
        }
        created = self.client.post(
            f"/emails/{self.email.id}/reply", json=payload, headers=self.headers
        )
        replay = self.client.post(
            f"/emails/{self.email.id}/reply", json=payload, headers=self.headers
        )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(created.json()["id"], replay.json()["id"])
        self.assertEqual(created.json()["status"], "pending")
        self.assertIsNone(created.json()["sent_at"])
        self.assertEqual(created.json()["thread_id"], str(self.thread.id))
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(Reply).where(
                Reply.user_id == self.user.id,
                Reply.idempotency_key == "reply-request-1",
            )),
            1,
        )

        fetched = self.client.get(f"/replies/{created.json()['id']}", headers=self.headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["status"], "pending")
        self.assertEqual(
            self.client.get(f"/replies/{created.json()['id']}", headers=self.other_headers).status_code,
            404,
        )

        conflict = self.client.post(
            f"/emails/{self.email.id}/reply",
            json={
                "confirmed": True,
                "idempotency_key": "reply-request-1",
                "body_text": "Un autre contenu",
            },
            headers=self.headers,
        )
        self.assertEqual(conflict.status_code, 409)

    def test_reply_requires_confirmation_key_and_content(self):
        base_url = f"/emails/{self.email.id}/reply"
        invalid_payloads = (
            {"confirmed": False, "idempotency_key": "key", "body_text": "Réponse"},
            {"confirmed": True, "body_text": "Réponse"},
            {"confirmed": True, "idempotency_key": " ", "body_text": "Réponse"},
            {"confirmed": True, "idempotency_key": "key"},
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                self.assertEqual(
                    self.client.post(base_url, json=payload, headers=self.headers).status_code,
                    422,
                )

        manual = self.client.post(
            base_url,
            json={
                "confirmed": True,
                "idempotency_key": "manual-reply",
                "body_text": "Réponse manuelle validée.",
            },
            headers=self.headers,
        )
        self.assertEqual(manual.status_code, 201)
        self.assertEqual(manual.json()["status"], "pending")
        self.assertIsNone(manual.json()["draft_id"])


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class ReplyConcurrencyTests(unittest.TestCase):
    def test_concurrent_requests_create_only_one_reply(self):
        engine = get_engine()
        with Session(engine) as db:
            user = User(email=f"{uuid4()}@example.test", password_hash="test-hash")
            db.add(user)
            db.flush()
            thread = Thread(user=user, gmail_thread_id=f"concurrent-{uuid4()}")
            db.add(thread)
            db.flush()
            email = DraftReplyApiTests.make_email(user, thread)
            db.add(email)
            db.commit()
            user_id, thread_id, email_id = user.id, thread.id, email.id
            token = create_access_token(user)

        payload = {
            "confirmed": True,
            "idempotency_key": f"concurrent-{uuid4()}",
            "body_text": "Une seule demande doit être créée.",
        }

        def request_reply(_):
            with TestClient(app) as client:
                return client.post(
                    f"/emails/{email_id}/reply",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                )

        try:
            with ThreadPoolExecutor(max_workers=8) as executor:
                responses = list(executor.map(request_reply, range(8)))
            self.assertTrue(all(response.status_code in {200, 201} for response in responses))
            self.assertEqual(len({response.json()["id"] for response in responses}), 1)
            with Session(engine) as db:
                count = db.scalar(select(func.count()).select_from(Reply).where(
                    Reply.user_id == user_id,
                    Reply.idempotency_key == payload["idempotency_key"],
                ))
                self.assertEqual(count, 1)
                reply = db.scalar(select(Reply).where(Reply.user_id == user_id))
                self.assertEqual(reply.status, "pending")
                self.assertIsNone(reply.sent_at)
        finally:
            with Session(engine) as db:
                db.execute(delete(Reply).where(Reply.user_id == user_id))
                db.execute(delete(Email).where(Email.id == email_id))
                db.execute(delete(Thread).where(Thread.id == thread_id))
                db.execute(delete(User).where(User.id == user_id))
                db.commit()
