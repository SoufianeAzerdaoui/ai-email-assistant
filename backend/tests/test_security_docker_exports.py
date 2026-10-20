"""Security checks for Docker settings and sanitized production workflow exports."""

import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = PROJECT_ROOT / "n8n" / "workflows"
PRODUCTION_EXPORTS = (
    "ai_classification.json",
    "ai_draft_generation.json",
    "gmail_send.json",
    "gmail_sync_batch_production.json",
    "workflow_error_handler.json",
)


class SecurityDockerExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflows = {
            name: json.loads((WORKFLOW_DIR / name).read_text(encoding="utf-8"))
            for name in PRODUCTION_EXPORTS
        }
        cls.compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    def test_production_exports_are_inactive_and_sanitized(self):
        email_pattern = re.compile(
            r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE
        )
        for name, workflow in self.workflows.items():
            with self.subTest(export=name):
                serialized = json.dumps(workflow)
                self.assertIs(workflow["active"], False)
                self.assertEqual(workflow.get("pinData"), {})
                self.assertEqual(workflow.get("tags"), [])
                self.assertNotRegex(serialized, email_pattern)
                self.assertNotIn("replace-with", serialized)
                self.assertNotIn("host.docker.internal", serialized)
                for node in workflow["nodes"]:
                    self.assertNotIn("credentials", node)
                    self.assertNotIn("webhookId", node)

    def test_gemini_exports_match_the_active_model(self):
        for name in ("ai_classification.json", "ai_draft_generation.json"):
            workflow = self.workflows[name]
            models = [
                node
                for node in workflow["nodes"]
                if "lmChatGoogleGemini" in node["type"]
            ]
            self.assertEqual(len(models), 1)
            self.assertEqual(
                models[0]["parameters"]["modelName"], "models/gemini-3.5-flash"
            )

    def test_batch_export_is_safe_to_import_but_represents_the_active_schedule(self):
        workflow = self.workflows["gmail_sync_batch_production.json"]
        nodes = {node["name"]: node for node in workflow["nodes"]}
        schedule = nodes["Toutes les 10 minutes"]

        self.assertFalse(schedule.get("disabled", False))
        self.assertEqual(
            schedule["parameters"]["rule"]["interval"][0]["minutesInterval"], 10
        )
        user_parameters = json.dumps(
            nodes["Configurer utilisateur"]["parameters"], ensure_ascii=False
        )
        self.assertIn("MAILFLOW_USER_ID", user_parameters)
        assignments = {
            assignment["name"]: assignment["value"]
            for assignment in nodes["Configurer utilisateur"]["parameters"][
                "assignments"
            ]["assignments"]
        }
        self.assertIs(assignments["test_mode"], False)
        for node_name in (
            "Lire curseur FastAPI",
            "Réserver synchronisation FastAPI",
            "Importer lot FastAPI",
            "Journaliser échec classification",
            "Valider curseur FastAPI",
        ):
            self.assertIn("$env.BACKEND_URL", nodes[node_name]["parameters"]["url"])

    def test_compose_has_short_retention_log_rotation_and_network_isolation(self):
        expected = (
            'image: docker.n8n.io/n8nio/n8n:2.43.6',
            'EXECUTIONS_DATA_PRUNE: "true"',
            'EXECUTIONS_DATA_MAX_AGE: ${EXECUTIONS_DATA_MAX_AGE:-72}',
            'EXECUTIONS_DATA_PRUNE_MAX_COUNT: ${EXECUTIONS_DATA_PRUNE_MAX_COUNT:-500}',
            'EXECUTIONS_DATA_SAVE_ON_ERROR: all',
            'EXECUTIONS_DATA_SAVE_ON_SUCCESS: none',
            'EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS: "false"',
            'N8N_EVENTBUS_LOGWRITER_KEEPLOGCOUNT:',
            'N8N_EVENTBUS_LOGWRITER_MAXFILESIZEINKB:',
            'max-size: "10m"',
            'max-file: "3"',
            'log_error_verbosity=terse',
            'mailflow_database:',
            'internal: true',
        )
        for setting in expected:
            with self.subTest(setting=setting):
                self.assertIn(setting, self.compose)

        self.assertNotIn("image: ${N8N_IMAGE", self.compose)
        self.assertIn('"127.0.0.1:${BACKEND_PORT:-8000}:8000"', self.compose)
        self.assertIn('"127.0.0.1:${FRONTEND_PORT:-3000}:3000"', self.compose)


if __name__ == "__main__":
    unittest.main()
