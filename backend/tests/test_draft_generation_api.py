"""Integration tests for asynchronous AI draft generation through n8n."""

import os
import unittest
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-32-characters")
os.environ.setdefault("WEBHOOK_SECRET", "classification-test-secret-at-least-32-chars")
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
from app.models import Draft, DraftGeneration, Email, Thread, User
from app.n8n_client import N8nDispatchError


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class DraftGenerationApiTests(unittest.TestCase):
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
            user_id=self.user.id,
            gmail_thread_id=f"gmail-thread-{uuid4()}",
            subject="Suivi du dossier",
        )
        self.other_thread = Thread(
            user_id=self.other_user.id,
            gmail_thread_id=f"gmail-thread-{uuid4()}",
            subject="Privé",
        )
        self.session.add_all([self.thread, self.other_thread])
        self.session.flush()
        now = datetime.now(timezone.utc)
        self.first_email = self.make_email(
            self.user, self.thread, "Premier message", now - timedelta(hours=1)
        )
        self.email = self.make_email(self.user, self.thread, "Relance", now)
        self.other_email = self.make_email(self.other_user, self.other_thread, "Privé", now)
        self.session.add_all([self.first_email, self.email, self.other_email])
        self.session.commit()

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        self.headers = {"Authorization": f"Bearer {create_access_token(self.user)}"}
        self.other_headers = {"Authorization": f"Bearer {create_access_token(self.other_user)}"}
        self.webhook_headers = {"X-Webhook-Secret": os.environ["WEBHOOK_SECRET"]}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    @staticmethod
    def make_email(user, thread, subject, received_at):
        return Email(
            user_id=user.id,
            thread_id=thread.id,
            gmail_message_id=f"message-{uuid4()}",
            sender="client@example.test",
            recipients=[user.email, "archive@example.test"],
            subject=subject,
            body_text=f"Contenu : {subject}",
            received_at=received_at,
            status="pending",
        )

    def start_generation(self, tone="formel"):
        with patch("app.draft_generation_routes.dispatch_draft_generation") as dispatch:
            response = self.client.post(
                f"/emails/{self.email.id}/draft/generate",
                json={"tone": tone},
                headers=self.headers,
            )
        return response, dispatch

    def test_dispatches_complete_context_and_can_be_polled(self):
        response, dispatch = self.start_generation()

        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data["status"], "generating")
        self.assertEqual(data["tone"], "formel")
        self.assertIsNone(data["draft_id"])
        dispatch.assert_called_once()
        payload = dispatch.call_args.args[0]
        self.assertEqual(payload["generation_id"], data["id"])
        self.assertEqual(payload["user_id"], str(self.user.id))
        self.assertEqual(payload["email_id"], str(self.email.id))
        self.assertEqual(payload["gmail_thread_id"], self.thread.gmail_thread_id)
        self.assertEqual(payload["recipients"], self.email.recipients)
        self.assertEqual(payload["reply_to"], [self.email.sender])
        self.assertEqual([item["email_id"] for item in payload["messages"]], [
            str(self.first_email.id), str(self.email.id),
        ])

        fetched = self.client.get(f"/draft-generations/{data['id']}", headers=self.headers)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json(), data)
        self.assertEqual(
            self.client.get(f"/draft-generations/{data['id']}", headers=self.other_headers).status_code,
            404,
        )

    def test_identical_active_generation_is_reused(self):
        with patch("app.draft_generation_routes.dispatch_draft_generation") as dispatch:
            first = self.client.post(
                f"/emails/{self.email.id}/draft/generate",
                json={"tone": "neutre"}, headers=self.headers,
            )
            duplicate = self.client.post(
                f"/emails/{self.email.id}/draft/generate",
                json={"tone": "neutre"}, headers=self.headers,
            )
            other_tone = self.client.post(
                f"/emails/{self.email.id}/draft/generate",
                json={"tone": "court"}, headers=self.headers,
            )

        self.assertEqual(first.status_code, 202)
        self.assertEqual(duplicate.status_code, 200)
        self.assertEqual(first.json()["id"], duplicate.json()["id"])
        self.assertEqual(other_tone.status_code, 202)
        self.assertNotEqual(first.json()["id"], other_tone.json()["id"])
        self.assertEqual(dispatch.call_count, 2)

    def test_ready_callback_creates_editable_ai_draft(self):
        generation, _ = self.start_generation("court")
        result = self.client.post(
            "/internal/webhooks/draft-result",
            headers=self.webhook_headers,
            json={
                "generation_id": generation.json()["id"],
                "user_id": str(self.user.id),
                "email_id": str(self.email.id),
                "status": "ready",
                "body_text": "Bonjour, votre demande est bien prise en compte.",
            },
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["status"], "ready")
        draft_id = result.json()["draft_id"]
        draft = self.session.get(Draft, draft_id)
        self.assertIsNotNone(draft)
        self.assertTrue(draft.generated_by_ai)
        self.assertEqual(draft.tone, "short")
        self.assertEqual(self.session.get(Email, self.email.id).status, "draft_ready")

        repeated = self.client.post(
            "/internal/webhooks/draft-result",
            headers=self.webhook_headers,
            json={
                "generation_id": generation.json()["id"],
                "user_id": str(self.user.id),
                "email_id": str(self.email.id),
                "status": "ready",
                "body_text": "Bonjour, votre demande est bien prise en compte.",
            },
        )
        self.assertEqual(repeated.json()["draft_id"], draft_id)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(Draft).where(Draft.id == draft.id)),
            1,
        )

        updated = self.client.put(
            f"/drafts/{draft_id}",
            headers=self.headers,
            json={"body_text": "Réponse relue et corrigée.", "tone": "neutre"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["body_text"], "Réponse relue et corrigée.")
        self.assertTrue(updated.json()["generated_by_ai"])

    def test_callback_security_isolation_and_validation(self):
        generation, _ = self.start_generation()
        payload = {
            "generation_id": generation.json()["id"],
            "user_id": str(self.user.id),
            "email_id": str(self.email.id),
            "status": "ready",
            "body_text": "Réponse générée.",
        }
        self.assertEqual(
            self.client.post("/internal/webhooks/draft-result", json=payload).status_code, 401
        )
        self.assertEqual(self.client.post(
            "/internal/webhooks/draft-result",
            headers={"X-Webhook-Secret": "wrong"}, json=payload,
        ).status_code, 401)
        self.assertEqual(self.client.post(
            "/internal/webhooks/draft-result",
            headers=self.webhook_headers,
            json={**payload, "user_id": str(self.other_user.id)},
        ).status_code, 404)
        self.assertEqual(self.client.post(
            "/internal/webhooks/draft-result",
            headers=self.webhook_headers,
            json={**payload, "body_text": " "},
        ).status_code, 422)
        self.assertEqual(self.client.post(
            "/internal/webhooks/draft-result",
            headers=self.webhook_headers,
            json={**payload, "status": "failed", "body_text": None},
        ).status_code, 422)

    def test_n8n_failure_is_persisted_without_creating_draft(self):
        with patch(
            "app.draft_generation_routes.dispatch_draft_generation",
            side_effect=N8nDispatchError("n8n request timed out"),
        ):
            response = self.client.post(
                f"/emails/{self.email.id}/draft/generate",
                json={"tone": "neutre"}, headers=self.headers,
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["status"], "failed")
        self.assertEqual(response.json()["error_message"], "n8n request timed out")
        self.assertIsNone(response.json()["draft_id"])

        recovered = self.client.post(
            "/internal/webhooks/draft-result",
            headers=self.webhook_headers,
            json={
                "generation_id": response.json()["id"],
                "user_id": str(self.user.id),
                "email_id": str(self.email.id),
                "status": "ready",
                "body_text": "Résultat arrivé après le timeout.",
            },
        )
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(recovered.json()["status"], "ready")

    def test_generate_authentication_validation_and_isolation(self):
        url = f"/emails/{self.email.id}/draft/generate"
        self.assertEqual(self.client.post(url, json={"tone": "formel"}).status_code, 401)
        self.assertEqual(self.client.post(
            url, json={"tone": "amical"}, headers=self.headers
        ).status_code, 422)
        self.assertEqual(self.client.post(
            url, json={"tone": "formel"}, headers=self.other_headers
        ).status_code, 404)


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class DraftGenerationConcurrencyTests(unittest.TestCase):
    def test_concurrent_identical_requests_create_one_generation(self):
        engine = get_engine()
        with Session(engine) as db:
            user = User(email=f"{uuid4()}@example.test", password_hash="test-hash")
            db.add(user)
            db.flush()
            thread = Thread(user_id=user.id, gmail_thread_id=f"concurrent-generation-{uuid4()}")
            db.add(thread)
            db.flush()
            email = DraftGenerationApiTests.make_email(
                user, thread, "Concurrence", datetime.now(timezone.utc)
            )
            db.add(email)
            db.commit()
            user_id, thread_id, email_id = user.id, thread.id, email.id
            token = create_access_token(user)

        def request_generation(_):
            with TestClient(app) as client:
                return client.post(
                    f"/emails/{email_id}/draft/generate",
                    json={"tone": "formel"},
                    headers={"Authorization": f"Bearer {token}"},
                )

        try:
            with patch("app.draft_generation_routes.dispatch_draft_generation") as dispatch:
                with ThreadPoolExecutor(max_workers=8) as executor:
                    responses = list(executor.map(request_generation, range(8)))
            self.assertTrue(all(response.status_code in {200, 202} for response in responses))
            self.assertEqual(len({response.json()["id"] for response in responses}), 1)
            self.assertEqual(dispatch.call_count, 1)
            with Session(engine) as db:
                count = db.scalar(select(func.count()).select_from(DraftGeneration).where(
                    DraftGeneration.user_id == user_id,
                    DraftGeneration.email_id == email_id,
                    DraftGeneration.tone == "formal",
                ))
                self.assertEqual(count, 1)
        finally:
            with Session(engine) as db:
                db.execute(delete(DraftGeneration).where(DraftGeneration.user_id == user_id))
                db.execute(delete(Email).where(Email.id == email_id))
                db.execute(delete(Thread).where(Thread.id == thread_id))
                db.execute(delete(User).where(User.id == user_id))
                db.commit()
