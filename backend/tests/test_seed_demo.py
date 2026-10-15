"""Integration test for the idempotent demo dataset."""

import os
import unittest
from collections import Counter
from uuid import uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Email, Thread, User
from scripts.seed_demo import DEMO_PREFIX, seed_demo


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is required")
class SeedDemoTests(unittest.TestCase):
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
        self.session.add(self.user)
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.transaction.rollback()
        self.connection.close()

    def test_seed_creates_thirty_emails_once(self):
        first_created = seed_demo(self.session, self.user)
        self.session.commit()
        second_created = seed_demo(self.session, self.user)
        self.session.commit()

        emails = self.session.scalars(select(Email).where(
            Email.user_id == self.user.id,
            Email.gmail_message_id.like(f"{DEMO_PREFIX}-message-%"),
        )).all()
        gmail_ids = [email.gmail_message_id for email in emails]
        messages_per_thread = Counter(email.thread_id for email in emails)
        thread_count = self.session.scalar(select(func.count()).select_from(Thread).where(
            Thread.user_id == self.user.id,
            Thread.gmail_thread_id.like(f"{DEMO_PREFIX}-thread-%"),
        ))

        self.assertEqual(first_created, 30)
        self.assertEqual(second_created, 0)
        self.assertEqual(len(emails), 30)
        self.assertEqual(len(set(gmail_ids)), 30)
        self.assertEqual(thread_count, 6)
        self.assertEqual(sorted(messages_per_thread.values()), [5, 5, 5, 5, 5, 5])
        self.assertGreater(len({email.category for email in emails}), 4)
        self.assertEqual({email.priority for email in emails}, {1, 2, 3})
        self.assertGreater(len({email.status for email in emails}), 2)
        self.assertGreater(len({email.sender for email in emails}), 6)
