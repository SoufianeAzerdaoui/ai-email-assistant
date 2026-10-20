"""Static checks for the importable, inactive Gmail send workflow."""

import json
import subprocess
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(__file__).resolve().parents[2] / "n8n/workflows/gmail_send.json"


class GmailSendWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.workflow = json.loads(cls.raw)
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}

    def prepare_result(self, response):
        request = {
            "reply_id": "11111111-1111-4111-8111-111111111111",
            "dispatch_id": "22222222-2222-4222-8222-222222222222",
            "user_id": "33333333-3333-4333-8333-333333333333",
            "email_id": "44444444-4444-4444-8444-444444444444",
            "idempotency_key": "send-test-1",
            "gmail_thread_id": "thread-original",
        }
        code = self.nodes["Préparer résultat Gmail"]["parameters"]["jsCode"]
        script = "\n".join((
            f"const $json = {json.dumps(response)};",
            f"const request = {json.dumps(request)};",
            "const $ = () => ({ item: { json: request } });",
            f"const result = (() => {{ {code} }})();",
            "process.stdout.write(JSON.stringify(result[0].json));",
        ))
        completed = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_workflow_is_importable_inactive_and_has_no_credentials(self):
        self.assertFalse(self.workflow["active"])
        self.assertEqual(len(self.nodes), len(self.workflow["nodes"]))
        self.assertNotIn("credentials", self.raw)
        self.assertNotIn("replace-with", self.raw)

    def test_webhook_gmail_call_and_callback_use_expected_contracts(self):
        webhook = self.nodes["Recevoir demande d’envoi"]
        self.assertEqual(webhook["parameters"]["path"], "gmail-send")
        self.assertEqual(webhook["parameters"]["authentication"], "headerAuth")
        self.assertIn(
            "payload.dispatch_id",
            self.nodes["Valider demande"]["parameters"]["jsCode"],
        )

        gmail = self.nodes["Envoyer réponse Gmail"]
        self.assertEqual(gmail["parameters"]["nodeCredentialType"], "gmailOAuth2")
        self.assertIn("/gmail/v1/users/me/messages/send", gmail["parameters"]["url"])
        self.assertNotIn("retryOnFail", gmail)
        headers = {
            item["name"]: item["value"]
            for item in gmail["parameters"]["headerParameters"]["parameters"]
        }
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Accept-Encoding"], "identity")
        response_options = gmail["parameters"]["options"]["response"]["response"]
        self.assertEqual(response_options["responseFormat"], "json")
        self.assertTrue(response_options["fullResponse"])
        # n8n 2.43.6 represents a JSON request with specifyBody/jsonBody and no
        # longer needs the redundant contentType field in this export.
        self.assertTrue(gmail["parameters"]["sendBody"])
        self.assertEqual(gmail["parameters"]["specifyBody"], "json")
        self.assertIn("jsonBody", gmail["parameters"])
        self.assertNotIn("rawContentType", gmail["parameters"])
        self.assertNotIn("body", gmail["parameters"])

        callback = self.nodes["Callback FastAPI"]
        self.assertEqual(callback["parameters"]["genericAuthType"], "httpHeaderAuth")
        self.assertIn(
            "/internal/webhooks/gmail-send-result", callback["parameters"]["url"]
        )
        self.assertTrue(callback["retryOnFail"])
        self.assertIn(
            "dispatch_id",
            self.nodes["Préparer résultat Gmail"]["parameters"]["jsCode"],
        )

        result_connections = self.workflow["connections"]["Résultat certain ?"]["main"]
        self.assertEqual(result_connections[0][0]["node"], "Callback FastAPI")
        self.assertEqual(result_connections[1][0]["node"], "Suspendre résultat ambigu")

    def test_mime_keeps_thread_context_and_stable_identifiers(self):
        mime_code = self.nodes["Préparer message MIME"]["parameters"]["jsCode"]
        self.assertIn("In-Reply-To", mime_code)
        self.assertIn("References", mime_code)
        self.assertIn("mailflow-' + request.reply_id", mime_code)
        gmail_body = self.nodes["Envoyer réponse Gmail"]["parameters"]["jsonBody"]
        self.assertIn("threadId", gmail_body)

    def test_http_200_with_gmail_id_is_sent(self):
        result = self.prepare_result({
            "statusCode": 200,
            "body": {
                "id": "gmail-sent-id",
                "threadId": "gmail-thread-id",
                "labelIds": ["SENT"],
            },
        })
        self.assertTrue(result["callback_allowed"])
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["gmail_message_id"], "gmail-sent-id")
        self.assertEqual(result["gmail_thread_id"], "gmail-thread-id")
        self.assertEqual(result["reply_id"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(result["dispatch_id"], "22222222-2222-4222-8222-222222222222")
        self.assertEqual(result["idempotency_key"], "send-test-1")

    def test_direct_gmail_json_with_id_is_sent(self):
        result = self.prepare_result({
            "id": "gmail-direct-id",
            "threadId": "gmail-direct-thread",
            "labelIds": ["SENT"],
        })
        self.assertTrue(result["callback_allowed"])
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["gmail_message_id"], "gmail-direct-id")
        self.assertEqual(result["gmail_thread_id"], "gmail-direct-thread")

    def test_http_error_is_failed_and_can_reach_callback(self):
        result = self.prepare_result({"statusCode": 400, "body": {"error": "invalid"}})
        self.assertTrue(result["callback_allowed"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("HTTP 400", result["error_message"])

    def test_http_503_is_ambiguous_and_never_retried(self):
        result = self.prepare_result({"statusCode": 503, "body": {"error": "unavailable"}})
        self.assertFalse(result["callback_allowed"])
        self.assertEqual(result["status"], "ambiguous")

    def test_ambiguous_http_200_is_suspended_without_failed_callback(self):
        result = self.prepare_result({
            "statusCode": 200,
            "body": {"_readableState": {}, "_outBuffer": []},
        })
        self.assertFalse(result["callback_allowed"])
        self.assertEqual(result["status"], "ambiguous")
        self.assertNotEqual(result["status"], "failed")
        self.assertEqual(result["reply_id"], "11111111-1111-4111-8111-111111111111")
        self.assertEqual(result["dispatch_id"], "22222222-2222-4222-8222-222222222222")


if __name__ == "__main__":
    unittest.main()
