"""Authentication integration tests against PostgreSQL."""

import os
import unittest
import warnings
from datetime import timedelta
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

from app.auth import create_access_token, hash_password
from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models import User


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        get_settings.cache_clear()
        cls.engine = create_engine(os.environ["TEST_DATABASE_URL"])

    @classmethod
    def tearDownClass(cls):
        get_settings.cache_clear()
        cls.engine.dispose()

    def setUp(self):
        self.connection = self.engine.connect()
        self.transaction = self.connection.begin()
        self.session = Session(self.connection, join_transaction_mode="create_savepoint")
        self.email = f"{uuid4()}@example.test"
        self.password = "correct horse battery staple"
        self.user = User(
            email=self.email,
            password_hash=hash_password(self.password),
            is_admin=True,
        )
        self.session.add(self.user)
        self.session.commit()

        def override_get_db():
            yield self.session

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def login(self):
        return self.client.post(
            "/auth/login", json={"email": self.email, "password": self.password}
        )

    def test_valid_login_and_me(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["token_type"], "bearer")

        me = self.client.get(
            "/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
        )
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json(), {
            "id": str(self.user.id), "email": self.email, "is_admin": True,
        })

    def test_invalid_login(self):
        wrong_password = self.client.post(
            "/auth/login", json={"email": self.email, "password": "wrong password"}
        )
        unknown_user = self.client.post(
            "/auth/login",
            json={"email": "unknown@example.test", "password": self.password},
        )
        self.assertEqual(wrong_password.status_code, 401)
        self.assertEqual(unknown_user.status_code, 401)

    def test_protected_route_requires_token(self):
        response = self.client.get("/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_expired_token_is_rejected(self):
        token = create_access_token(self.user, expires_delta=timedelta(seconds=-1))
        response = self.client.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        self.assertEqual(response.status_code, 401)

    def test_logout_revokes_issued_token(self):
        token = self.login().json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        logout = self.client.post("/auth/logout", headers=headers)
        self.assertEqual(logout.status_code, 204)
        self.assertEqual(self.client.get("/auth/me", headers=headers).status_code, 401)
        self.assertEqual(self.client.post("/auth/logout", headers=headers).status_code, 401)
