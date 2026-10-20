"""Static and executable checks for the isolated Gemini benchmark export."""

import ast
import base64
import json
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = PROJECT_ROOT / "n8n" / "workflows" / "gemini_classification_benchmark.json"
CLASSIFICATION_PATH = PROJECT_ROOT / "n8n" / "workflows" / "ai_classification.json"
SEED_PATH = PROJECT_ROOT / "scripts" / "seed_demo.py"


def load_seed_threads():
    tree = ast.parse(SEED_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "THREADS"
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("THREADS was not found in scripts/seed_demo.py")


class GeminiClassificationBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        cls.reference = json.loads(CLASSIFICATION_PATH.read_text(encoding="utf-8"))
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}
        cls.reference_nodes = {node["name"]: node for node in cls.reference["nodes"]}
        cls.connections = cls.workflow["connections"]

    def run_javascript(self, node_name, declarations):
        code = self.nodes[node_name]["parameters"]["jsCode"]
        script = "\n".join((
            declarations,
            f"const result = (() => {{ {code} }})();",
            "process.stdout.write(JSON.stringify(result));",
        ))
        completed = subprocess.run(
            ["node", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_export_is_inactive_manual_and_has_a_complete_graph(self):
        names = [node["name"] for node in self.workflow["nodes"]]
        identifiers = [node["id"] for node in self.workflow["nodes"]]
        targets = {
            edge["node"]
            for connections in self.connections.values()
            for output_group in connections.values()
            for output in output_group
            for edge in output
        }
        types = {node["type"] for node in self.workflow["nodes"]}

        self.assertIs(self.workflow["active"], False)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(targets - set(names), set())
        self.assertEqual(set(self.connections) - set(names), set())
        self.assertIn("n8n-nodes-base.manualTrigger", types)
        self.assertNotIn("n8n-nodes-base.scheduleTrigger", types)
        self.assertNotIn("n8n-nodes-base.webhook", types)
        self.assertNotIn("n8n-nodes-base.httpRequest", types)

    def test_dataset_exactly_matches_seed_demo(self):
        expected = []
        for thread_index, thread in enumerate(load_seed_threads(), start=1):
            for message_index, body in enumerate(thread["bodies"], start=1):
                expected.append({
                    "fixture_id": (
                        f"demo-seed-v1-message-{thread_index:02d}-{message_index:02d}"
                    ),
                    "subject": (
                        thread["subject"]
                        if message_index == 1
                        else f"Re: {thread['subject']}"
                    ),
                    "body": body,
                })

        result = self.run_javascript(
            "Charger les 30 e-mails seed_demo",
            "const $json = { benchmark_mode: 'full', benchmark_started_ms: 1, "
            "logical_call_limit: 60, transport_attempt_limit: 120, message_limit: 30 };",
        )
        actual = [
            {
                "fixture_id": item["json"]["fixture_id"],
                "subject": item["json"]["subject"],
                "body": item["json"]["body"],
            }
            for item in result
        ]

        self.assertEqual(len(actual), 30)
        self.assertEqual(actual, expected)

    def test_prompts_temperature_and_validators_match_production_export(self):
        for node_name in ("Classification Gemini", "Nouvelle tentative Gemini"):
            with self.subTest(node=node_name):
                benchmark = self.nodes[node_name]["parameters"]
                production = self.reference_nodes[node_name]["parameters"]
                self.assertEqual(benchmark["promptType"], production["promptType"])
                self.assertEqual(benchmark["text"], production["text"])
                self.assertEqual(
                    [message["message"] for message in benchmark["messages"]["messageValues"]],
                    [message["message"] for message in production["messages"]["messageValues"]],
                )
                self.assertEqual(benchmark["batching"], production["batching"])
        for node_name in ("Valider JSON initial", "Valider JSON nouvelle tentative"):
            with self.subTest(node=node_name):
                self.assertEqual(
                    self.nodes[node_name]["parameters"],
                    self.reference_nodes[node_name]["parameters"],
                )
        model = self.nodes["Google Gemini Chat Model"]
        self.assertEqual(model["parameters"]["modelName"], "models/gemini-3.5-flash")
        self.assertEqual(model["parameters"]["options"]["temperature"], 0.1)

    def test_single_mode_is_default_and_batch_mode_is_capped_at_ten(self):
        code = self.nodes["Configurer benchmark"]["parameters"]["jsCode"]
        self.assertIn("const benchmarkMode = 'single';", code)
        self.assertIn("const batchSize = 10;", code)
        self.assertIn("benchmarkMode === 'single' ? 1 : batchSize", code)
        self.assertIn("batchSize > 10", code)
        self.assertIn("results: []", code)
        self.assertIn("logical_call_limit: messageLimit * 2", code)
        self.assertIn("transport_attempt_limit: messageLimit * 4", code)

        single = self.run_javascript("Configurer benchmark", "")
        self.assertEqual(single[0]["json"]["message_limit"], 1)
        self.assertEqual(single[0]["json"]["logical_call_limit"], 2)
        self.assertEqual(single[0]["json"]["transport_attempt_limit"], 4)

    def test_loader_resumes_from_checkpoint_in_groups_of_ten(self):
        base = {
            "benchmark_mode": "batch",
            "benchmark_started_ms": 1,
            "logical_call_limit": 20,
            "transport_attempt_limit": 40,
            "message_limit": 10,
            "checkpoint_results": [],
            "checkpoint_groups": [],
        }
        first = self.run_javascript(
            "Charger les 30 e-mails seed_demo", f"const $json = {json.dumps(base)};"
        )
        self.assertEqual(len(first), 10)

        base["checkpoint_results"] = [
            {"fixture_id": item["json"]["fixture_id"]} for item in first
        ]
        second = self.run_javascript(
            "Charger les 30 e-mails seed_demo", f"const $json = {json.dumps(base)};"
        )
        self.assertEqual(len(second), 10)
        self.assertTrue(
            set(item["json"]["fixture_id"] for item in first).isdisjoint(
                item["json"]["fixture_id"] for item in second
            )
        )

    def test_processing_is_sequential_and_rate_limited(self):
        loop = self.nodes["Traiter un message à la fois"]
        pause = self.nodes["Pause 5 secondes"]
        self.assertEqual(loop["parameters"]["batchSize"], 1)
        self.assertEqual(pause["parameters"]["amount"], 5)
        self.assertEqual(pause["parameters"]["unit"], "seconds")
        self.assertEqual(
            self.connections["Pause 5 secondes"]["main"][0][0]["node"],
            "Traiter un message à la fois",
        )

    def test_transport_retries_are_bounded(self):
        expected = {
            "Classification Gemini": (2, 5000),
            "Nouvelle tentative Gemini": (2, 10000),
        }
        for node_name, (tries, wait) in expected.items():
            node = self.nodes[node_name]
            with self.subTest(node=node_name):
                self.assertTrue(node["retryOnFail"])
                self.assertTrue(node["continueOnFail"])
                self.assertEqual(node["maxTries"], tries)
                self.assertEqual(node["waitBetweenTries"], wait)

    def test_metrics_distinguish_invalid_json_from_technical_errors(self):
        all_results = [
            {
                "json": {
                    "fixture_id": f"fixture-{index}",
                    "first_attempt_valid": index < 24,
                    "first_attempt_technical_error": index == 29,
                    "retry_used": 24 <= index < 29,
                    "retry_valid": 24 <= index < 27,
                    "fallback_used": index >= 27,
                    "technical_error": index in {28, 29},
                    "quota_error": index == 29,
                    "http_429_error": index == 29,
                    "http_503_error": index == 28,
                    "initial_json_invalid": 24 <= index < 29,
                    "retry_json_invalid": index == 27,
                    "error_code": "http_429" if index == 29 else None,
                    "duration_ms": 100,
                    "benchmark_started_ms": 0,
                    "logical_calls": 2 if 24 <= index < 29 else 1,
                    "benchmark_mode": "batch",
                    "checkpoint_results": [],
                    "checkpoint_groups": [],
                }
            }
            for index in range(30)
        ]
        previous_results = [
            {
                key: value
                for key, value in item["json"].items()
                if key
                not in {
                    "benchmark_started_ms",
                    "benchmark_mode",
                    "checkpoint_results",
                    "checkpoint_groups",
                }
            }
            for item in all_results[:20]
        ]
        results = all_results[20:]
        for item in results:
            item["json"]["checkpoint_results"] = previous_results
            item["json"]["checkpoint_groups"] = [
                {"group_number": 1, "message_count": 10, "duration_ms": 1000},
                {"group_number": 2, "message_count": 10, "duration_ms": 1000},
            ]
        aggregated = self.run_javascript(
            "Calculer métriques finales",
            f"const items = {json.dumps(results)}; const $input = {{ all: () => items }};",
        )[0]["json"]

        self.assertEqual(aggregated["total_messages"], 30)
        self.assertEqual(aggregated["initial_valid"], 24)
        self.assertEqual(aggregated["initial_invalid"], 5)
        self.assertEqual(aggregated["retries_used"], 5)
        self.assertEqual(aggregated["corrections_succeeded"], 3)
        self.assertEqual(aggregated["fallbacks_used"], 3)
        self.assertEqual(aggregated["technical_errors"], 2)
        self.assertEqual(aggregated["http_429_errors"], 1)
        self.assertEqual(aggregated["http_503_errors"], 1)
        self.assertEqual(aggregated["json_invalid_after_retry"], 1)
        self.assertEqual(aggregated["initial_success_percentage"], 80.0)
        self.assertTrue(aggregated["completed"])
        self.assertLessEqual(
            aggregated["logical_model_calls"], aggregated["logical_call_limit"]
        )

    def test_partial_checkpoint_has_no_final_rate(self):
        results = [
            {
                "json": {
                    "fixture_id": f"fixture-{index}",
                    "first_attempt_valid": True,
                    "retry_used": False,
                    "retry_valid": False,
                    "fallback_used": False,
                    "first_attempt_technical_error": False,
                    "technical_error": False,
                    "quota_error": False,
                    "http_429_error": False,
                    "http_503_error": False,
                    "initial_json_invalid": False,
                    "retry_json_invalid": False,
                    "error_code": None,
                    "duration_ms": 100,
                    "benchmark_started_ms": 0,
                    "logical_calls": 1,
                    "benchmark_mode": "batch",
                    "checkpoint_results": [],
                    "checkpoint_groups": [],
                }
            }
            for index in range(10)
        ]
        aggregated = self.run_javascript(
            "Calculer métriques finales",
            f"const items = {json.dumps(results)}; const $input = {{ all: () => items }};",
        )[0]["json"]

        self.assertEqual(aggregated["total_messages"], 10)
        self.assertEqual(aggregated["remaining_messages"], 20)
        self.assertFalse(aggregated["completed"])
        self.assertIsNone(aggregated["initial_success_percentage"])
        self.assertEqual(len(aggregated["checkpoint"]["results"]), 10)

    def test_each_group_exports_a_resumable_checkpoint_and_csv(self):
        report = {
            "benchmark": "resumable_30",
            "total_messages": 10,
            "results": [
                {
                    "fixture_id": "demo-seed-v1-message-01-01",
                    "first_attempt_valid": True,
                    "initial_json_invalid": False,
                    "retry_used": False,
                    "retry_valid": False,
                    "retry_json_invalid": False,
                    "fallback_used": False,
                    "first_attempt_technical_error": False,
                    "technical_error": False,
                    "http_429_error": False,
                    "http_503_error": False,
                    "error_code": None,
                    "duration_ms": 100,
                }
            ],
            "checkpoint": {
                "version": 1,
                "dataset_id": "seed-demo-v1",
                "model": "models/gemini-3.5-flash",
                "results": [{"fixture_id": "demo-seed-v1-message-01-01"}],
                "groups": [{"group_number": 1, "message_count": 1}],
            },
        }
        exported = self.run_javascript(
            "Créer exports checkpoint et CSV", f"const $json = {json.dumps(report)};"
        )[0]

        checkpoint = json.loads(
            base64.b64decode(exported["binary"]["checkpoint"]["data"])
        )
        csv = base64.b64decode(exported["binary"]["results"]["data"]).decode()
        self.assertEqual(checkpoint, report["checkpoint"])
        self.assertEqual(
            exported["binary"]["checkpoint"]["fileName"],
            "gemini-benchmark-checkpoint-10.json",
        )
        self.assertIn("fixture_id", csv)
        self.assertNotIn("subject", csv)
        self.assertNotIn("body", csv)

    def test_export_contains_no_message_content_secret_or_credential_id(self):
        serialized = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertNotIn("credentials", serialized)
        self.assertNotIn("WEBHOOK_SECRET", serialized)
        self.assertNotIn("apiKey", serialized)
        self.assertNotIn("localhost:8000", serialized)
        self.assertNotIn("internal/webhooks", serialized)

        csv_code = self.nodes["Créer exports checkpoint et CSV"]["parameters"]["jsCode"]
        self.assertIn("fixture_id", csv_code)
        for sensitive_field in (
            "subject",
            "body",
            "category",
            "summary",
            "expected_action",
        ):
            with self.subTest(field=sensitive_field):
                self.assertNotIn(sensitive_field, csv_code)


if __name__ == "__main__":
    unittest.main()
