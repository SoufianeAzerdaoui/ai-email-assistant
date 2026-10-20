"""Static and executable checks for automatic n8n classification."""

import json
import subprocess
import unittest
from pathlib import Path


WORKFLOW_DIR = Path(__file__).resolve().parents[2] / "n8n/workflows"


class AiClassificationWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(
            (WORKFLOW_DIR / "ai_classification.json").read_text(encoding="utf-8")
        )
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}
        cls.connections = cls.workflow["connections"]
        cls.error_workflow = json.loads(
            (WORKFLOW_DIR / "workflow_error_handler.json").read_text(encoding="utf-8")
        )

    def test_production_webhook_and_manual_trigger_are_both_available(self):
        webhook = self.nodes["Recevoir classification"]
        self.assertEqual(webhook["parameters"]["path"], "classification")
        self.assertEqual(webhook["parameters"]["authentication"], "headerAuth")
        # n8n 2.43.6 omits responseMode when the default onReceived mode is used.
        self.assertEqual(
            webhook["parameters"].get("responseMode", "onReceived"), "onReceived"
        )
        self.assertIn("Mailflow - Entrée n8n", webhook["notes"])
        self.assertIn("Déclenchement manuel", self.nodes)
        self.assertEqual(
            self.connections["Recevoir classification"]["main"][0][0]["node"],
            "Entrée classification",
        )

    def test_gemini_retries_are_limited_with_staged_backoff(self):
        first = self.nodes["Classification Gemini"]
        retry = self.nodes["Nouvelle tentative Gemini"]
        for node in (first, retry):
            self.assertTrue(node["retryOnFail"])
            self.assertEqual(node["maxTries"], 2)
            self.assertTrue(node["continueOnFail"])
        self.assertEqual(first["waitBetweenTries"], 5000)
        self.assertEqual(retry["waitBetweenTries"], 10000)

    def test_invalid_or_failed_gemini_uses_review_fallback(self):
        code = self.nodes["Fallback à vérifier"]["parameters"]["jsCode"]

        def run(first_error, retry_error):
            script = "\n".join((
                "const $input = { all: () => [{ json: {} }] };",
                "const values = " + json.dumps({
                    "Classification Gemini": {"error": first_error} if first_error else {},
                    "Nouvelle tentative Gemini": {"error": retry_error} if retry_error else {},
                }) + ";",
                "const $ = (name) => ({ item: { json: values[name] } });",
                f"const result = (() => {{ {code} }})();",
                "process.stdout.write(JSON.stringify(result[0].json));",
            ))
            completed = subprocess.run(
                ["node", "-e", script], check=True, capture_output=True, text=True
            )
            return json.loads(completed.stdout)

        invalid = run(None, None)
        unavailable = run("429", "503")
        self.assertTrue(invalid["classification"]["needs_review"])
        self.assertEqual(invalid["error_type"], "invalid_gemini_output")
        self.assertEqual(unavailable["error_type"], "gemini_unavailable")

    def test_callback_and_error_logging_are_bounded_and_isolated(self):
        callback = self.nodes["Enregistrer classification"]
        logger = self.nodes["Journaliser erreur classification"]
        self.assertTrue(callback["retryOnFail"])
        self.assertEqual(callback["maxTries"], 3)
        self.assertTrue(callback["continueOnFail"])
        self.assertIn("Mailflow - Vers FastAPI", callback["notes"])
        self.assertIn("/internal/webhooks/workflow-errors", logger["parameters"]["url"])
        self.assertNotIn("raw", logger["parameters"]["body"].lower())
        fallback_targets = {
            edge["node"]
            for edge in self.connections["Fallback à vérifier"]["main"][0]
        }
        self.assertEqual(fallback_targets, {
            "Enregistrer classification", "Journaliser erreur classification"
        })

    def test_exports_are_inactive_and_contain_no_credentials_or_secrets(self):
        for workflow in (self.workflow, self.error_workflow):
            raw = json.dumps(workflow)
            self.assertFalse(workflow["active"])
            self.assertTrue(all("credentials" not in node for node in workflow["nodes"]))
            self.assertNotIn("replace-with", raw)
        error_nodes = {node["name"]: node for node in self.error_workflow["nodes"]}
        sanitizer = error_nodes["Préparer erreur sûre"]["parameters"]["jsCode"]
        self.assertNotIn("event.execution.error.message", sanitizer)
        self.assertNotIn("event.execution.error.stack", sanitizer)
        self.assertIn("MAILFLOW_USER_ID", sanitizer)

        event = {
            "workflow": {"id": "workflow-1", "name": "Mailflow test"},
            "execution": {
                "id": "execution-1",
                "lastNodeExecuted": "Gemini",
                "error": {
                    "message": "secret-value-must-not-leak",
                    "stack": "Authorization: bearer secret-value-must-not-leak",
                },
            },
        }
        script = "\n".join((
            f"const $json = {json.dumps(event)};",
            "const $env = { MAILFLOW_USER_ID: '11111111-1111-4111-8111-111111111111' };",
            f"const result = (() => {{ {sanitizer} }})();",
            "process.stdout.write(JSON.stringify(result[0].json));",
        ))
        completed = subprocess.run(
            ["node", "-e", script], check=True, capture_output=True, text=True
        )
        safe_output = completed.stdout
        self.assertNotIn("secret-value-must-not-leak", safe_output)
        self.assertNotIn("Authorization", safe_output)


if __name__ == "__main__":
    unittest.main()
