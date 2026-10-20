"""Static and executable checks for the experimental batched Gmail Sync export."""

import json
import math
import subprocess
import unittest
from pathlib import Path


WORKFLOW_DIR = Path(__file__).resolve().parents[2] / "n8n" / "workflows"
CANDIDATE_PATH = WORKFLOW_DIR / "gmail_sync_batch_candidate.json"
SOURCE_PATH = WORKFLOW_DIR / "gmail_sync.json"
HARNESS_PATH = (
    Path(__file__).resolve().parents[2]
    / "n8n"
    / "tests"
    / "gmail_sync_batch_manual_harness.json"
)
HTTP_HARNESS_PATH = (
    Path(__file__).resolve().parents[2]
    / "n8n"
    / "tests"
    / "gmail_sync_batch_http_integration.json"
)
HTTP_COMPOSE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docker-compose.gmail-batch-test.yml"
)


class GmailSyncBatchCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
        cls.source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}
        cls.source_nodes = {node["name"]: node for node in cls.source["nodes"]}
        cls.connections = cls.workflow["connections"]

    def targets(self, node_name, output_index):
        return [
            edge["node"]
            for edge in self.connections[node_name]["main"][output_index]
        ]

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

    @staticmethod
    def normalized_messages(count):
        sync = {
            "user_id": "11111111-1111-4111-8111-111111111111",
            "execution_id": "22222222-2222-4222-8222-222222222222",
            "idempotency_key": "gmail-sync:test",
            "cursor_after": "200",
            "test_mode": False,
        }
        return [
            {
                "json": {
                    "_sync": sync,
                    "gmail_message_id": f"message-{index}",
                    "gmail_thread_id": f"thread-{index // 3}",
                    "message_id": f"<message-{index}@example.test>",
                    "sender": "sender@example.test",
                    "recipients": ["mailflow@example.test"],
                    "subject": f"Message {index}",
                    "body_text": "Contenu fictif.",
                    "body_html": None,
                    "received_at": "2026-10-19T10:00:00Z",
                }
            }
            for index in range(count)
        ]

    def test_export_is_valid_inactive_and_has_a_complete_graph(self):
        names = [node["name"] for node in self.workflow["nodes"]]
        identifiers = [node["id"] for node in self.workflow["nodes"]]
        targets = {
            edge["node"]
            for connections in self.connections.values()
            for output in connections["main"]
            for edge in output
        }

        self.assertEqual(self.workflow["name"], "Mailflow - Gmail Sync Batch Candidate")
        self.assertIs(self.workflow["active"], False)
        self.assertIs(self.nodes["Toutes les 10 minutes"]["disabled"], True)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(targets - set(names), set())
        self.assertEqual(set(self.connections) - set(names), set())
        self.assertTrue(all("credentials" not in node for node in self.workflow["nodes"]))

    def test_existing_export_remains_unitary(self):
        self.assertIn("Importer message FastAPI", self.source_nodes)
        self.assertEqual(
            self.source_nodes["Traiter un message à la fois"]["parameters"]["batchSize"],
            1,
        )
        self.assertNotIn("Importer lot FastAPI", self.source_nodes)

    def test_fastapi_routes_and_user_id_parameter_are_preserved(self):
        expected_urls = {
            "Lire curseur FastAPI": (
                "=http://host.docker.internal:8000/internal/webhooks/gmail/"
                "sync-state/{{ $json.user_id }}"
            ),
            "Réserver synchronisation FastAPI": (
                "http://host.docker.internal:8000/internal/webhooks/gmail/sync-state/claim"
            ),
            "Importer lot FastAPI": (
                "http://host.docker.internal:8000/internal/webhooks/gmail/messages"
            ),
            "Journaliser échec classification": (
                "http://host.docker.internal:8000/internal/webhooks/workflow-errors"
            ),
            "Valider curseur FastAPI": (
                "http://host.docker.internal:8000/internal/webhooks/gmail/sync-state/commit"
            ),
        }
        for node_name, expected_url in expected_urls.items():
            with self.subTest(node=node_name):
                self.assertEqual(self.nodes[node_name]["parameters"]["url"], expected_url)
        self.assertNotIn("method", self.nodes["Lire curseur FastAPI"]["parameters"])

    def test_gmail_pagination_history_and_retries_are_unchanged(self):
        unchanged_nodes = (
            "Lister 50 IDs Gmail (TEST)",
            "Lister historique Gmail",
            "Lire profil Gmail",
            "Lister tous les IDs Gmail",
            "Préparer historique Gmail",
            "Préparer liste complète",
            "Préparer requête détail",
            "Récupérer détail Gmail",
            "Analyser réponse Gmail",
            "Retry quota possible ?",
            "Attendre backoff exponentiel",
            "Incrémenter tentative",
        )
        for node_name in unchanged_nodes:
            with self.subTest(node=node_name):
                self.assertEqual(
                    self.nodes[node_name]["parameters"],
                    self.source_nodes[node_name]["parameters"],
                )

    def test_details_remain_sequential_and_rate_limited(self):
        detail_loop = self.nodes["Traiter un détail Gmail à la fois"]
        self.assertEqual(
            self.nodes["Traiter un lot de messages"]["parameters"]["batchSize"], 10
        )
        self.assertEqual(detail_loop["parameters"]["batchSize"], 1)
        self.assertEqual(
            detail_loop["parameters"]["options"]["reset"],
            "={{ Number.isInteger($json.attempt) }}",
        )
        self.assertEqual(
            self.nodes["Attendre 2,5 secondes Gmail"]["parameters"]["amount"], 2.5
        )
        self.assertEqual(
            self.targets("Attendre 2,5 secondes Gmail", 0),
            ["Traiter un détail Gmail à la fois"],
        )

    def test_batches_of_one_ten_fifteen_and_thirty(self):
        batch_size = self.nodes["Traiter un lot de messages"]["parameters"]["batchSize"]
        expected_sizes = {
            1: [1],
            10: [10],
            15: [10, 5],
            30: [10, 10, 10],
        }

        for total, expected in expected_sizes.items():
            messages = self.normalized_messages(total)
            chunks = [messages[index:index + batch_size] for index in range(0, total, batch_size)]
            actual = []
            for chunk in chunks:
                declarations = "\n".join((
                    f"const items = {json.dumps(chunk)};",
                    "const $input = { all: () => items };",
                ))
                result = self.run_javascript("Préparer lot import", declarations)
                actual.append(len(result[0]["json"]["messages"]))
            with self.subTest(total=total):
                self.assertEqual(actual, expected)
                self.assertEqual(len(chunks), math.ceil(total / 10))
                self.assertLessEqual(max(actual), 10)

    def test_batch_rejects_mixed_sync_contexts(self):
        messages = self.normalized_messages(2)
        messages[1]["json"]["_sync"] = {
            **messages[1]["json"]["_sync"],
            "execution_id": "33333333-3333-4333-8333-333333333333",
        }
        declarations = "\n".join((
            f"const items = {json.dumps(messages)};",
            "const $input = { all: () => items };",
        ))

        with self.assertRaises(subprocess.CalledProcessError):
            self.run_javascript("Préparer lot import", declarations)

    def test_simulated_gmail_message_keeps_sync_context_and_content(self):
        sync = self.normalized_messages(1)[0]["json"]["_sync"]
        encode = lambda value: __import__("base64").urlsafe_b64encode(
            value.encode("utf-8")
        ).decode("ascii").rstrip("=")
        gmail_response = {
            "id": "gmail-simulated-1",
            "threadId": "thread-simulated-1",
            "internalDate": "1792396800000",
            "payload": {
                "headers": [
                    {"name": "From", "value": "Client <client@example.test>"},
                    {"name": "To", "value": "mailflow@example.test"},
                    {"name": "Subject", "value": "Message simulé"},
                    {"name": "Message-ID", "value": "<simulated@example.test>"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "filename": "",
                        "body": {"data": encode("Contenu Gmail simulé.")},
                    }
                ],
            },
        }
        declarations = (
            f"const $json = {json.dumps({'_sync': sync, 'gmail_message_id': 'requested-id', 'gmail_response': gmail_response})};"
        )

        result = self.run_javascript("Normaliser message Gmail", declarations)[0]["json"]

        self.assertEqual(result["_sync"], sync)
        self.assertEqual(result["gmail_message_id"], "gmail-simulated-1")
        self.assertEqual(result["gmail_thread_id"], "thread-simulated-1")
        self.assertEqual(result["subject"], "Message simulé")
        self.assertEqual(result["body_text"], "Contenu Gmail simulé.")

    def test_recovered_classification_tasks_flow_when_imported_count_is_zero(self):
        batch = self.run_javascript(
            "Préparer lot import",
            "\n".join((
                f"const items = {json.dumps(self.normalized_messages(2))};",
                "const $input = { all: () => items };",
            )),
        )[0]["json"]
        tasks = [
            {
                "user_id": batch["_sync"]["user_id"],
                "email_id": f"00000000-0000-4000-8000-00000000000{index}",
                "subject": f"Doublon {index}",
                "body": "Classification manquante.",
            }
            for index in range(2)
        ]
        response = {
            "received_count": 2,
            "imported_count": 0,
            "duplicate_count": 2,
            "classification_tasks": tasks,
        }
        preserved = self.run_javascript(
            "Conserver résultat import",
            "\n".join((
                f"const batch = {json.dumps(batch)};",
                "const $ = () => ({ item: { json: batch } });",
                f"const $json = {json.dumps(response)};",
            )),
        )[0]["json"]
        expanded = self.run_javascript(
            "Développer classifications",
            f"const $json = {json.dumps(preserved)};",
        )

        self.assertEqual(preserved["imported_count"], 0)
        self.assertEqual(preserved["classification_tasks"], tasks)
        self.assertEqual(
            [item["json"]["classification_task"] for item in expanded], tasks
        )

    def test_import_failure_cannot_reach_cursor_commit(self):
        importer = self.nodes["Importer lot FastAPI"]
        self.assertTrue(importer["retryOnFail"])
        self.assertEqual(importer["maxTries"], 3)
        self.assertNotIn("continueOnFail", importer)
        self.assertEqual(
            self.targets("Importer lot FastAPI", 0), ["Conserver résultat import"]
        )
        incoming_to_commit_gate = {
            source
            for source, connections in self.connections.items()
            for output in connections["main"]
            for edge in output
            if edge["node"] == "Commit curseur autorisé ?"
        }
        self.assertEqual(
            incoming_to_commit_gate,
            {"Messages à traiter ?", "Traiter un lot de messages"},
        )

    def test_test_mode_imports_without_committing_cursor(self):
        condition = self.nodes["Commit curseur autorisé ?"]["parameters"][
            "conditions"
        ]["conditions"][0]["leftValue"]
        self.assertIn("test_mode !== true", condition)
        self.assertEqual(self.targets("Commit curseur autorisé ?", 1), [])
        self.assertEqual(
            self.targets("Traiter un lot de messages", 0),
            ["Commit curseur autorisé ?"],
        )

    def test_zero_messages_commits_only_for_normal_mode(self):
        self.assertEqual(
            self.targets("Messages à traiter ?", 1), ["Commit curseur autorisé ?"]
        )
        normal_sync = {
            "user_id": "11111111-1111-4111-8111-111111111111",
            "execution_id": "22222222-2222-4222-8222-222222222222",
            "idempotency_key": "gmail-sync:empty",
            "cursor_before": "100",
            "cursor_after": "101",
            "test_mode": False,
        }
        declarations = "\n".join((
            f"const items = {json.dumps([{'json': {'_empty': True, '_sync': normal_sync}}])};",
            "const $input = { all: () => items };",
        ))
        prepared = self.run_javascript("Préparer commit curseur", declarations)[0]["json"]

        self.assertEqual(prepared["imported_count"], 0)
        self.assertEqual(prepared["skipped_not_found"], 0)
        self.assertEqual(prepared["user_id"], normal_sync["user_id"])
        self.assertEqual(prepared["execution_id"], normal_sync["execution_id"])

    def test_batch_counters_and_sync_identifiers_reach_commit(self):
        sync = self.normalized_messages(1)[0]["json"]["_sync"]
        sync["cursor_before"] = "100"
        items = [
            {"json": {"_sync": sync, "imported_count": 10, "skipped_not_found": 0}},
            {"json": {"_sync": sync, "imported_count": 4, "skipped_not_found": 1}},
            {"json": {"_sync": sync, "imported_count": 0, "skipped_not_found": 2}},
        ]
        declarations = "\n".join((
            f"const items = {json.dumps(items)};",
            "const $input = { all: () => items };",
        ))

        prepared = self.run_javascript("Préparer commit curseur", declarations)[0]["json"]

        self.assertEqual(prepared["user_id"], sync["user_id"])
        self.assertEqual(prepared["execution_id"], sync["execution_id"])
        self.assertEqual(prepared["cursor_after"], sync["cursor_after"])
        self.assertEqual(prepared["imported_count"], 14)
        self.assertEqual(prepared["skipped_not_found"], 3)

    def test_classification_tasks_are_processed_sequentially_after_import(self):
        importer_body = self.nodes["Importer lot FastAPI"]["parameters"]["jsonBody"]
        dispatch = self.nodes["Déclencher classification IA"]
        classification_loop = self.nodes["Traiter une classification à la fois"]
        self.assertIn("messages: $json.messages", importer_body)
        self.assertEqual(classification_loop["parameters"]["batchSize"], 1)
        self.assertEqual(
            classification_loop["parameters"]["options"]["reset"],
            "={{ $json.classification_dispatch_failed === undefined }}",
        )
        self.assertEqual(
            dispatch["parameters"]["url"],
            "http://127.0.0.1:5678/webhook/classification",
        )
        self.assertTrue(dispatch["retryOnFail"])
        self.assertTrue(dispatch["continueOnFail"])
        self.assertEqual(
            self.targets("Terminer lot", 0), ["Traiter un lot de messages"]
        )

    def test_credentials_and_error_connections_are_explicit(self):
        fastapi_nodes = (
            "Lire curseur FastAPI",
            "Réserver synchronisation FastAPI",
            "Importer lot FastAPI",
            "Journaliser échec classification",
            "Valider curseur FastAPI",
        )
        gmail_nodes = (
            "Lister 50 IDs Gmail (TEST)",
            "Lister historique Gmail",
            "Lire profil Gmail",
            "Lister tous les IDs Gmail",
            "Récupérer détail Gmail",
        )
        for node_name in fastapi_nodes:
            with self.subTest(node=node_name):
                parameters = self.nodes[node_name]["parameters"]
                self.assertEqual(parameters["authentication"], "genericCredentialType")
                self.assertEqual(parameters["genericAuthType"], "httpHeaderAuth")
                self.assertIn("Mailflow - Vers FastAPI", self.nodes[node_name]["notes"])
        for node_name in gmail_nodes:
            with self.subTest(node=node_name):
                parameters = self.nodes[node_name]["parameters"]
                self.assertEqual(parameters["authentication"], "predefinedCredentialType")
                self.assertEqual(parameters["nodeCredentialType"], "gmailOAuth2Api")
        self.assertIn(
            "Mailflow - Entrée n8n", self.nodes["Déclencher classification IA"]["notes"]
        )
        self.assertEqual(
            self.targets("Retry quota possible ?", 1), ["Arrêter sans avancer curseur"]
        )
        self.assertEqual(
            self.targets("Classification acceptée ?", 1),
            ["Journaliser échec classification"],
        )


class GmailSyncBatchManualHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(HARNESS_PATH.read_text(encoding="utf-8"))
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}
        cls.connections = cls.workflow["connections"]
        cls.candidate = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
        cls.candidate_nodes = {node["name"]: node for node in cls.candidate["nodes"]}

    def targets(self, node_name, output_index):
        return [
            edge["node"]
            for edge in self.connections[node_name]["main"][output_index]
        ]

    def test_harness_is_inactive_complete_and_has_no_external_nodes(self):
        names = [node["name"] for node in self.workflow["nodes"]]
        identifiers = [node["id"] for node in self.workflow["nodes"]]
        targets = {
            edge["node"]
            for connections in self.connections.values()
            for output in connections["main"]
            for edge in output
        }

        self.assertIs(self.workflow["active"], False)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(targets - set(names), set())
        self.assertEqual(set(self.connections) - set(names), set())
        self.assertTrue(all("credentials" not in node for node in self.workflow["nodes"]))
        self.assertFalse(
            any(node["type"] == "n8n-nodes-base.httpRequest" for node in self.workflow["nodes"])
        )
        self.assertFalse(
            any(node["type"] == "n8n-nodes-base.scheduleTrigger" for node in self.workflow["nodes"])
        )

    def test_harness_uses_the_candidate_loop_configuration(self):
        for node_name in (
            "Traiter un lot de messages",
            "Traiter un détail Gmail à la fois",
            "Traiter une classification à la fois",
        ):
            with self.subTest(node=node_name):
                self.assertEqual(
                    self.nodes[node_name]["parameters"],
                    self.candidate_nodes[node_name]["parameters"],
                )

    def test_harness_defines_all_reproducible_scenarios(self):
        code = self.nodes["Configurer scénario"]["parameters"]["jsCode"]
        for scenario in (
            "batch_15",
            "batch_30",
            "fail_second_batch",
            "zero",
            "test_15",
            "zero_test",
        ):
            with self.subTest(scenario=scenario):
                self.assertIn(f"{scenario}:", code)
        self.assertIn("const selected = 'batch_15';", code)
        self.assertIn("fail_batch: 2", code)

    def test_expected_batch_sizes_and_counts(self):
        for total, expected in ((15, [10, 5]), (30, [10, 10, 10])):
            batches = [
                min(10, total - offset)
                for offset in range(0, total, 10)
            ]
            with self.subTest(total=total):
                self.assertEqual(batches, expected)
                self.assertEqual(sum(batches), total)

    def test_failure_in_second_batch_has_no_path_to_commit(self):
        import_code = self.nodes["Simuler import FastAPI"]["parameters"]["jsCode"]
        self.assertIn("fail_batch === batch.batch_number", import_code)
        self.assertIn("throw new Error", import_code)
        self.assertEqual(
            self.targets("Simuler import FastAPI", 0), ["Développer classifications"]
        )
        incoming_to_commit = {
            source
            for source, connections in self.connections.items()
            for output in connections["main"]
            for edge in output
            if edge["node"] == "Commit curseur autorisé ?"
        }
        self.assertEqual(
            incoming_to_commit,
            {"Vérifier résultats des lots", "Préparer résultat zéro message"},
        )

    def test_test_mode_and_zero_message_paths_are_explicit(self):
        condition = self.nodes["Commit curseur autorisé ?"]["parameters"][
            "conditions"
        ]["conditions"][0]["leftValue"]
        self.assertIn("test_mode !== true", condition)
        self.assertEqual(
            self.targets("Messages à traiter ?", 1),
            ["Préparer résultat zéro message"],
        )
        self.assertEqual(
            self.targets("Commit curseur autorisé ?", 1),
            ["Confirmer absence de commit"],
        )
        self.assertIn(
            "commit_called: false",
            self.nodes["Confirmer absence de commit"]["parameters"]["jsCode"],
        )


class GmailSyncBatchHttpIntegrationSetupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(HTTP_HARNESS_PATH.read_text(encoding="utf-8"))
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}
        cls.connections = cls.workflow["connections"]
        candidate = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))
        cls.candidate_nodes = {node["name"]: node for node in candidate["nodes"]}

    def targets(self, node_name, output_index):
        return [
            edge["node"]
            for edge in self.connections[node_name]["main"][output_index]
        ]

    def test_http_harness_graph_is_complete_and_inactive(self):
        names = [node["name"] for node in self.workflow["nodes"]]
        identifiers = [node["id"] for node in self.workflow["nodes"]]
        targets = {
            edge["node"]
            for connections in self.connections.values()
            for output in connections["main"]
            for edge in output
        }
        self.assertIs(self.workflow["active"], False)
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(identifiers), len(set(identifiers)))
        self.assertEqual(targets - set(names), set())
        self.assertEqual(set(self.connections) - set(names), set())
        self.assertFalse(any("credentials" in node for node in self.workflow["nodes"]))

    def test_only_isolated_fastapi_http_calls_exist(self):
        http_nodes = [
            node for node in self.workflow["nodes"]
            if node["type"] == "n8n-nodes-base.httpRequest"
        ]
        self.assertEqual(len(http_nodes), 4)
        for node in http_nodes:
            with self.subTest(node=node["name"]):
                serialized = json.dumps(node["parameters"])
                self.assertIn("GMAIL_BATCH_TEST_BACKEND_URL", serialized)
                self.assertIn("GMAIL_BATCH_TEST_WEBHOOK_SECRET", serialized)
                self.assertNotIn("gmail.googleapis.com", serialized)
                self.assertNotIn("gemini", serialized.lower())
                self.assertNotIn("host.docker.internal", serialized)

    def test_http_harness_uses_candidate_loop_configuration(self):
        for node_name in (
            "Traiter un lot de messages",
            "Traiter un détail Gmail à la fois",
            "Traiter une classification à la fois",
        ):
            self.assertEqual(
                self.nodes[node_name]["parameters"],
                self.candidate_nodes[node_name]["parameters"],
            )

    def test_second_batch_failure_is_an_actual_fastapi_422(self):
        importer = self.nodes["Importer lot FastAPI de test"]
        body = importer["parameters"]["jsonBody"]
        self.assertIn("fail_batch === $json.batch_number", body)
        self.assertIn('sender: \\\"\\\"', json.dumps(body))
        self.assertTrue(importer["retryOnFail"])
        self.assertEqual(importer["maxTries"], 3)
        self.assertNotIn("continueOnFail", importer)
        self.assertEqual(
            self.targets("Importer lot FastAPI de test", 0),
            ["Conserver résultat import HTTP"],
        )

    def test_test_mode_reads_state_and_cannot_commit(self):
        self.assertEqual(
            self.targets("Mode TEST ?", 0), ["Lire état FastAPI de test"]
        )
        self.assertEqual(
            self.targets("Mode TEST ?", 1),
            ["Réserver synchronisation FastAPI de test"],
        )
        condition = self.nodes["Commit curseur autorisé ?"]["parameters"][
            "conditions"
        ]["conditions"][0]["leftValue"]
        self.assertIn("test_mode !== true", condition)
        self.assertEqual(
            self.targets("Commit curseur autorisé ?", 1),
            ["Confirmer absence de commit"],
        )

    def test_classification_is_counted_without_external_dispatch(self):
        node = self.nodes["Simuler classification acceptée"]
        self.assertEqual(node["type"], "n8n-nodes-base.code")
        self.assertIn("classification_status_code: 202", node["parameters"]["jsCode"])
        self.assertFalse(any(
            "classification" in node["name"].lower()
            and node["type"] == "n8n-nodes-base.httpRequest"
            for node in self.workflow["nodes"]
        ))

    def test_compose_uses_dedicated_ports_volumes_and_internal_network(self):
        compose = HTTP_COMPOSE_PATH.read_text(encoding="utf-8")
        for target, published in ((5432, 55432), (8000, 18000), (5678, 15679)):
            with self.subTest(port=published):
                self.assertIn(
                    f'target: {target}\n        published: "{published}"\n'
                    "        host_ip: 127.0.0.1",
                    compose,
                )
        self.assertIn("mailflow_gmail_batch_test", compose)
        self.assertIn("gmail_batch_postgres_data", compose)
        self.assertIn("gmail_batch_n8n_data", compose)
        self.assertIn("internal: true", compose)
        self.assertNotIn("env_file:", compose)


if __name__ == "__main__":
    unittest.main()
