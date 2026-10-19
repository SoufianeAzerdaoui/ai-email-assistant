"""Unit tests for the authenticated FastAPI to n8n Gmail dispatch."""

import unittest
from unittest.mock import Mock, patch

import httpx

from app.config import get_n8n_draft_settings, get_n8n_gmail_send_settings
from app.n8n_client import (
    N8nDispatchError,
    N8nDispatchUncertainError,
    dispatch_draft_generation,
    dispatch_gmail_reply,
)


PAYLOAD = {
    "reply_id": "11111111-1111-4111-8111-111111111111",
    "dispatch_id": "44444444-4444-4444-8444-444444444444",
    "user_id": "22222222-2222-4222-8222-222222222222",
    "email_id": "33333333-3333-4333-8333-333333333333",
    "idempotency_key": "request-1",
    "gmail_message_id": "gmail-original",
    "gmail_thread_id": "gmail-thread",
    "rfc_message_id": "<original@example.test>",
    "recipient": "client@example.test",
    "subject": "Demande",
    "body_text": "Bonjour, voici ma réponse.",
}


class N8nGmailSendClientTests(unittest.TestCase):
    def setUp(self):
        get_n8n_draft_settings.cache_clear()
        get_n8n_gmail_send_settings.cache_clear()
        self.environment = patch.dict(
            "os.environ",
            {
                "N8N_GMAIL_SEND_WEBHOOK_URL": "http://127.0.0.1:5678/webhook/gmail-send",
                "N8N_DRAFT_WEBHOOK_URL": "http://127.0.0.1:5678/webhook/draft-generation",
                "N8N_WEBHOOK_SECRET": "n8n-inbound-secret-at-least-32-characters",
                "N8N_REQUEST_TIMEOUT_SECONDS": "7",
            },
        )
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        get_n8n_draft_settings.cache_clear()
        get_n8n_gmail_send_settings.cache_clear()

    @patch("app.n8n_client.httpx.post")
    def test_uses_n8n_secret_and_expected_payload(self, post):
        post.return_value = Mock()
        dispatch_gmail_reply(PAYLOAD)

        post.assert_called_once_with(
            "http://127.0.0.1:5678/webhook/gmail-send",
            json=PAYLOAD,
            headers={
                "X-Webhook-Secret": "n8n-inbound-secret-at-least-32-characters"
            },
            timeout=7.0,
        )
        post.return_value.raise_for_status.assert_called_once_with()

    @patch("app.n8n_client.httpx.post")
    def test_draft_generation_uses_same_inbound_n8n_secret(self, post):
        post.return_value = Mock()
        payload = {
            "generation_id": "11111111-1111-4111-8111-111111111111",
            "user_id": "22222222-2222-4222-8222-222222222222",
            "email_id": "33333333-3333-4333-8333-333333333333",
            "thread_id": "44444444-4444-4444-8444-444444444444",
            "gmail_thread_id": "gmail-thread",
            "subject": "Demande",
            "recipients": ["user@example.test"],
            "reply_to": ["client@example.test"],
            "tone": "neutre",
            "messages": [],
        }
        dispatch_draft_generation(payload)

        post.assert_called_once_with(
            "http://127.0.0.1:5678/webhook/draft-generation",
            json=payload,
            headers={
                "X-Webhook-Secret": "n8n-inbound-secret-at-least-32-characters"
            },
            timeout=7.0,
        )

    def test_test_webhook_urls_are_rejected(self):
        with patch.dict("os.environ", {
            "N8N_DRAFT_WEBHOOK_URL": "http://127.0.0.1:5678/webhook-test/draft-generation",
            "N8N_GMAIL_SEND_WEBHOOK_URL": "http://127.0.0.1:5678/webhook-test/gmail-send",
        }):
            get_n8n_draft_settings.cache_clear()
            get_n8n_gmail_send_settings.cache_clear()
            with self.assertRaisesRegex(RuntimeError, "production /webhook/"):
                get_n8n_draft_settings()
            with self.assertRaisesRegex(RuntimeError, "production /webhook/"):
                get_n8n_gmail_send_settings()

    @patch("app.n8n_client.httpx.post")
    def test_timeout_is_uncertain_but_http_rejection_is_retryable(self, post):
        post.side_effect = httpx.TimeoutException("timeout")
        with self.assertRaises(N8nDispatchUncertainError):
            dispatch_gmail_reply(PAYLOAD)

        request = httpx.Request("POST", "http://127.0.0.1:5678/webhook/gmail-send")
        response = httpx.Response(503, request=request)
        post.side_effect = None
        post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503", request=request, response=response
        )
        with self.assertRaises(N8nDispatchError) as raised:
            dispatch_gmail_reply(PAYLOAD)
        self.assertNotIsInstance(raised.exception, N8nDispatchUncertainError)


if __name__ == "__main__":
    unittest.main()
