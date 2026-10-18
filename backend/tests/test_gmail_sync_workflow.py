import json
import subprocess
import unittest
from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[2] / "n8n" / "workflows" / "gmail_sync.json"
)


class GmailSyncWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        cls.nodes = {node["name"]: node for node in cls.workflow["nodes"]}
        cls.connections = cls.workflow["connections"]

    def targets(self, node_name, output_index):
        outputs = self.connections[node_name]["main"]
        return [edge["node"] for edge in outputs[output_index]]

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

    def test_test_mode_is_safe_by_default_and_limited_to_fifty_total(self):
        assignments = self.nodes["Configurer utilisateur"]["parameters"][
            "assignments"
        ]["assignments"]
        test_mode = next(item for item in assignments if item["name"] == "test_mode")
        test_list = self.nodes["Lister 50 IDs Gmail (TEST)"]["parameters"]
        query = {
            item["name"]: item["value"]
            for item in test_list["queryParameters"]["parameters"]
        }

        self.assertIs(test_mode["value"], True)
        self.assertEqual(test_mode["type"], "boolean")
        self.assertEqual(query["maxResults"], "50")
        self.assertNotIn("pagination", test_list["options"])

    def test_test_path_imports_without_committing_cursor(self):
        self.assertEqual(
            self.targets("Mode TEST ?", 0),
            ["Lister 50 IDs Gmail (TEST)"],
        )
        test_context = self.nodes["Préparer liste TEST"]["parameters"]["jsCode"]
        commit_condition = self.nodes["Commit curseur autorisé ?"]["parameters"][
            "conditions"
        ]["conditions"][0]["leftValue"]

        self.assertIn("test_mode: true", test_context)
        self.assertIn("cursor_after: null", test_context)
        self.assertIn("messages.length > 50", test_context)
        self.assertIn("test_mode !== true", commit_condition)
        self.assertEqual(
            self.targets("Traiter un message à la fois", 0),
            ["Commit curseur autorisé ?"],
        )
        self.assertEqual(self.targets("Commit curseur autorisé ?", 1), [])

    def test_normal_full_and_incremental_sync_are_preserved(self):
        full_list = self.nodes["Lister tous les IDs Gmail"]["parameters"]
        incremental_context = self.nodes["Préparer historique Gmail"]["parameters"][
            "jsCode"
        ]
        full_context = self.nodes["Préparer liste complète"]["parameters"][
            "jsCode"
        ]
        full_query = {
            item["name"]: item["value"]
            for item in full_list["queryParameters"]["parameters"]
        }
        pagination = full_list["options"]["pagination"]["pagination"]
        history = self.nodes["Lister historique Gmail"]["parameters"]
        history_query = {
            item["name"]: item["value"]
            for item in history["queryParameters"]["parameters"]
        }
        history_pagination = history["options"]["pagination"]["pagination"]

        self.assertEqual(full_list["url"], "https://gmail.googleapis.com/gmail/v1/users/me/messages")
        self.assertEqual(full_query["maxResults"], "500")
        self.assertEqual(pagination["paginationMode"], "updateAParameterInEachRequest")
        self.assertEqual(pagination["requestInterval"], 1000)
        self.assertEqual(history_query["maxResults"], "500")
        self.assertEqual(
            history_pagination["paginationMode"],
            "updateAParameterInEachRequest",
        )
        self.assertIn("nextPageToken", history_pagination["completeExpression"])
        self.assertEqual(history_pagination["requestInterval"], 1000)
        self.assertTrue(all(
            node["type"] != "n8n-nodes-base.gmail"
            for node in self.workflow["nodes"]
        ))
        self.assertIn("test_mode: false", incremental_context)
        self.assertIn("test_mode: false", full_context)
        self.assertEqual(
            self.targets("Mode TEST ?", 1),
            ["Curseur présent ?"],
        )
        self.assertEqual(
            self.targets("Commit curseur autorisé ?", 0),
            ["Préparer commit curseur"],
        )
        self.assertEqual(
            self.targets("Préparer commit curseur", 0),
            ["Valider curseur FastAPI"],
        )

    def test_details_are_sequential_and_rate_limited(self):
        loop = self.nodes["Traiter un message à la fois"]
        wait = self.nodes["Attendre 2,5 secondes"]["parameters"]
        detail = self.nodes["Récupérer détail Gmail"]["parameters"]
        per_minute = 60 / wait["amount"]

        self.assertEqual(loop["type"], "n8n-nodes-base.splitInBatches")
        self.assertEqual(loop["parameters"]["batchSize"], 1)
        self.assertGreaterEqual(per_minute, 20)
        self.assertLessEqual(per_minute, 30)
        self.assertEqual(detail["queryParameters"]["parameters"][0], {
            "name": "format",
            "value": "full",
        })
        response = detail["options"]["response"]["response"]
        self.assertIs(response["fullResponse"], True)
        self.assertIs(response["neverError"], True)
        self.assertEqual(
            self.targets("Attendre 2,5 secondes", 0),
            ["Traiter un message à la fois"],
        )

    def test_quota_errors_use_bounded_exponential_backoff(self):
        analyzer = self.nodes["Analyser réponse Gmail"]["parameters"]["jsCode"]
        retry_condition = self.nodes["Retry quota possible ?"]["parameters"][
            "conditions"
        ]["conditions"][0]["leftValue"]
        backoff = self.nodes["Attendre backoff exponentiel"]["parameters"]

        self.assertIn("statusCode === 429", analyzer)
        self.assertIn("statusCode === 403", analyzer)
        self.assertIn("userRateLimitExceeded", analyzer)
        self.assertIn("2 ** attempt", analyzer)
        self.assertIn("Math.min(32", analyzer)
        self.assertIn("Math.random()", analyzer)
        self.assertIn("attempt < 6", retry_condition)
        self.assertEqual(backoff["amount"], "={{ $json.backoff_seconds }}")
        self.assertEqual(
            self.targets("Retry quota possible ?", 1),
            ["Arrêter sans avancer curseur"],
        )

    def test_messages_get_404_is_counted_skipped_and_returns_to_loop(self):
        request = {
            "gmail_message_id": "deleted-message",
            "attempt": 0,
            "_sync": {"user_id": "user", "test_mode": False},
        }
        declarations = "\n".join((
            f"const request = {json.dumps(request)};",
            "const $ = () => ({ item: { json: request } });",
            "const $json = { statusCode: 404, body: { error: { message: 'Requested entity was not found' } } };",
        ))
        analyzed = self.run_javascript("Analyser réponse Gmail", declarations)[0]["json"]
        skipped = self.run_javascript(
            "Comptabiliser message introuvable",
            f"const $json = {json.dumps(analyzed)};",
        )[0]["json"]

        self.assertTrue(analyzed["not_found"])
        self.assertFalse(analyzed["retryable"])
        self.assertEqual(skipped["skipped_not_found"], 1)
        self.assertEqual(skipped["imported_count"], 0)
        self.assertEqual(self.targets("Détail récupéré ?", 1), ["Message introuvable ?"])
        self.assertEqual(
            self.targets("Message introuvable ?", 0),
            ["Comptabiliser message introuvable"],
        )
        self.assertEqual(
            self.targets("Comptabiliser message introuvable", 0),
            ["Attendre 2,5 secondes"],
        )
        self.assertNotIn("Importer message FastAPI", {
            edge["node"]
            for output in self.connections["Message introuvable ?"]["main"]
            for edge in output
        })

    def test_history_404_expires_cursor_while_other_detail_errors_stop(self):
        history_condition = self.nodes["Curseur expiré ?"]["parameters"][
            "conditions"
        ]["conditions"][0]["leftValue"]
        self.assertIn("statusCode === 404", history_condition)
        self.assertEqual(self.targets("Curseur expiré ?", 0), ["Lire profil Gmail"])
        self.assertEqual(self.targets("Curseur expiré ?", 1), ["Préparer historique Gmail"])
        self.assertEqual(
            self.targets("Message introuvable ?", 1),
            ["Retry quota possible ?"],
        )
        self.assertEqual(
            self.targets("Retry quota possible ?", 1),
            ["Arrêter sans avancer curseur"],
        )

    def test_commit_aggregates_skips_only_after_completed_loop(self):
        sync = {
            "user_id": "11111111-1111-4111-8111-111111111111",
            "cursor_before": "10",
            "cursor_after": "20",
            "test_mode": False,
        }
        items = [
            {"json": {"_sync": sync, "imported_count": 1}},
            {"json": {"_sync": sync, "imported_count": 0, "skipped_not_found": 1}},
        ]
        declarations = "\n".join((
            f"const items = {json.dumps(items)};",
            "const $input = { all: () => items };",
            "const $execution = { id: 'execution-1' };",
        ))
        result = self.run_javascript("Préparer commit curseur", declarations)[0]["json"]
        commit_body = self.nodes["Valider curseur FastAPI"]["parameters"]["body"]

        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(result["skipped_not_found"], 1)
        self.assertNotIn("skipped_not_found", commit_body)
        self.assertEqual(
            self.targets("Traiter un message à la fois", 0),
            ["Commit curseur autorisé ?"],
        )

    def test_cursor_commit_only_follows_completed_loop(self):
        self.assertEqual(
            self.targets("Traiter un message à la fois", 0),
            ["Commit curseur autorisé ?"],
        )
        self.assertNotIn("Arrêter sans avancer curseur", self.connections)
        self.assertEqual(
            self.targets("Importer message FastAPI", 0),
            ["Conserver résultat import"],
        )
        incoming_to_gate = {
            source
            for source, connections in self.connections.items()
            for output in connections["main"]
            for edge in output
            if edge["node"] == "Commit curseur autorisé ?"
        }
        self.assertEqual(
            incoming_to_gate,
            {"Messages à traiter ?", "Traiter un message à la fois"},
        )

    def test_schedule_stays_disabled_and_no_credentials_are_embedded(self):
        self.assertIs(self.workflow["active"], False)
        self.assertIs(self.nodes["Toutes les 10 minutes"]["disabled"], True)
        self.assertTrue(all("credentials" not in node for node in self.workflow["nodes"]))


if __name__ == "__main__":
    unittest.main()
