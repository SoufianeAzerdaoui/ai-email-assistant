import os
import unittest
import warnings
from uuid import uuid4

os.environ.setdefault("JWT_SECRET", "test-secret-that-is-at-least-32-characters")
os.environ.setdefault("WEBHOOK_SECRET", "gmail-sync-test-secret-at-least-32-chars")
warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import get_webhook_secret
from app.database import get_db
from app.main import app
from app.models import SyncExecution, SyncState, User


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class GmailSyncStateWebhookTests(unittest.TestCase):
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

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def get_state(self, user_id=None, headers=None):
        return self.client.get(
            f"/internal/webhooks/gmail/sync-state/{user_id or self.user.id}",
            headers=self.headers if headers is None else headers,
        )

    def commit(self, **overrides):
        payload = {
            "user_id": str(self.user.id),
            "cursor_before": None,
            "cursor_after": "gmail-history-100",
            "idempotency_key": "gmail-sync-run-1",
            "imported_count": 12,
            **overrides,
        }
        return self.client.post(
            "/internal/webhooks/gmail/sync-state/commit",
            headers=self.headers,
            json=payload,
        )

    def test_reads_empty_state_and_commits_cursor(self):
        empty = self.get_state()
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json(), {
            "user_id": str(self.user.id),
            "cursor": None,
            "last_synced_at": None,
        })

        response = self.commit()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["cursor"], "gmail-history-100")
        self.assertEqual(response.json()["imported_count"], 12)
        state = self.session.get(SyncState, self.user.id)
        self.assertEqual(state.cursor, "gmail-history-100")
        self.assertIsNotNone(state.last_synced_at)
        execution = self.session.get(SyncExecution, response.json()["execution_id"])
        self.assertEqual(execution.status, "succeeded")
        self.assertEqual(execution.cursor_before, None)
        self.assertEqual(execution.cursor_after, "gmail-history-100")

    def test_commit_is_idempotent(self):
        first = self.commit()
        second = self.commit()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())
        self.assertEqual(self.session.scalar(
            select(func.count()).select_from(SyncExecution).where(
                SyncExecution.user_id == self.user.id
            )
        ), 1)

    def test_advances_only_from_current_cursor(self):
        self.assertEqual(self.commit().status_code, 200)
        advanced = self.commit(
            cursor_before="gmail-history-100",
            cursor_after="gmail-history-150",
            idempotency_key="gmail-sync-run-2",
            imported_count=3,
        )
        stale = self.commit(
            cursor_before="gmail-history-100",
            cursor_after="gmail-history-175",
            idempotency_key="gmail-sync-run-stale",
            imported_count=1,
        )

        self.assertEqual(advanced.status_code, 200)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.session.get(SyncState, self.user.id).cursor, "gmail-history-150")
        self.assertEqual(self.session.scalar(
            select(func.count()).select_from(SyncExecution).where(
                SyncExecution.user_id == self.user.id
            )
        ), 2)

    def test_rejects_reused_key_with_different_data(self):
        self.assertEqual(self.commit().status_code, 200)
        response = self.commit(imported_count=13)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.session.get(SyncState, self.user.id).cursor, "gmail-history-100")

    def test_requires_secret_and_existing_user(self):
        self.assertEqual(self.get_state(headers={}).status_code, 401)
        self.assertEqual(self.get_state(headers={"X-Webhook-Secret": "wrong"}).status_code, 401)
        self.assertEqual(self.get_state(user_id=uuid4()).status_code, 404)
        response = self.commit(user_id=str(uuid4()))
        self.assertEqual(response.status_code, 404)

    def test_state_is_isolated_by_user(self):
        self.assertEqual(self.commit().status_code, 200)
        other = self.get_state(user_id=self.other_user.id)

        self.assertEqual(other.status_code, 200)
        self.assertIsNone(other.json()["cursor"])

    def test_validates_commit_payload(self):
        self.assertEqual(self.commit(cursor_after=" ").status_code, 422)
        self.assertEqual(self.commit(idempotency_key=" ").status_code, 422)
        self.assertEqual(self.commit(imported_count=-1).status_code, 422)
        self.assertIsNone(self.session.get(SyncState, self.user.id))
