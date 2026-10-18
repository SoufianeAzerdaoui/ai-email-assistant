"""Static audit of n8n webhook directions and credential assignments."""

import json
import unittest
from pathlib import Path


WORKFLOW_DIR = Path(__file__).resolve().parents[2] / "n8n/workflows"
INBOUND_CREDENTIAL = "Mailflow - Entrée n8n"
OUTBOUND_CREDENTIAL = "Mailflow - Vers FastAPI"


class WebhookDirectionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {}
        for filename in (
            "ai_draft_generation.json",
            "gmail_send.json",
            "gmail_sync.json",
        ):
            raw = (WORKFLOW_DIR / filename).read_text(encoding="utf-8")
            cls.workflows[filename] = (raw, json.loads(raw))

    @staticmethod
    def nodes(workflow):
        return {node["name"]: node for node in workflow["nodes"]}

    def test_inbound_webhooks_use_production_paths_and_inbound_credential(self):
        expected = {
            "ai_draft_generation.json": ("Recevoir génération", "draft-generation"),
            "gmail_send.json": ("Recevoir demande d’envoi", "gmail-send"),
        }
        for filename, (node_name, path) in expected.items():
            with self.subTest(filename=filename):
                raw, workflow = self.workflows[filename]
                node = self.nodes(workflow)[node_name]
                self.assertEqual(node["parameters"]["authentication"], "headerAuth")
                self.assertEqual(node["parameters"]["path"], path)
                self.assertIn(INBOUND_CREDENTIAL, node["notes"])
                self.assertIn("N8N_WEBHOOK_SECRET", node["notes"])
                self.assertNotIn("webhook-test", raw)

    def test_callbacks_use_only_the_outbound_fastapi_credential(self):
        callback_nodes = {
            "ai_draft_generation.json": ["Callback FastAPI"],
            "gmail_send.json": ["Callback FastAPI"],
            "gmail_sync.json": [
                "Lire curseur FastAPI",
                "Importer message FastAPI",
                "Valider curseur FastAPI",
            ],
        }
        for filename, names in callback_nodes.items():
            _, workflow = self.workflows[filename]
            nodes = self.nodes(workflow)
            for name in names:
                with self.subTest(filename=filename, node=name):
                    node = nodes[name]
                    self.assertEqual(
                        node["parameters"]["authentication"], "genericCredentialType"
                    )
                    self.assertEqual(
                        node["parameters"]["genericAuthType"], "httpHeaderAuth"
                    )
                    self.assertIn(OUTBOUND_CREDENTIAL, node["notes"])
                    self.assertIn("WEBHOOK_SECRET", node["notes"])

    def test_exports_do_not_embed_or_overwrite_credentials(self):
        for filename, (raw, workflow) in self.workflows.items():
            with self.subTest(filename=filename):
                self.assertTrue(all("credentials" not in node for node in workflow["nodes"]))
                self.assertNotIn('"credentials"', raw)

    def test_gmail_callback_failure_cannot_reenter_messages_send(self):
        _, workflow = self.workflows["gmail_send.json"]
        nodes = self.nodes(workflow)
        callback = nodes["Callback FastAPI"]
        gmail_send = nodes["Envoyer réponse Gmail"]

        self.assertTrue(callback["retryOnFail"])
        self.assertNotIn("continueOnFail", callback)
        self.assertNotIn("retryOnFail", gmail_send)
        self.assertNotIn("Callback FastAPI", workflow["connections"])


if __name__ == "__main__":
    unittest.main()
