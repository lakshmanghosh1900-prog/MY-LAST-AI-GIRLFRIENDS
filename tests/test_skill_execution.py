from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from my_last_ai_girlfriends.governance import GovernanceError
from my_last_ai_girlfriends.http_api import MyLastAIGirlfriendsHTTPServer
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService

from test_budget_service import make_config


def definition(path: str = "notes.md") -> dict:
    return {
        "schema_version": 1,
        "steps": [{"tool": "file.read_text", "arguments": {"path": path}}],
    }


def approve(service: MyLastAIGirlfriendsService, capabilities: list[str] | None = None, manifest: dict | None = None) -> dict:
    skill = service.create_skill("local reader", "1.0.0", "local-test", capabilities or ["read-only-file"], manifest or definition())
    service.transition_skill(skill["id"], "REVIEW")
    service.transition_skill(skill["id"], "APPROVED")
    return skill


class SkillExecutionTests(unittest.TestCase):
    def test_approved_declarative_skill_reads_only_local_text_and_audits_hashes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            (root / "workspace" / "notes.md").write_text("private local note", encoding="utf-8")
            service = MyLastAIGirlfriendsService(make_config(root))
            try:
                skill = approve(service)
                result = service.execute_skill(skill["id"])
                self.assertEqual(result["status"], "SUCCEEDED")
                self.assertEqual(result["output"], "private local note")
                self.assertFalse(result["truncated"])
                self.assertEqual(service.db.connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
                self.assertEqual(service.db.connection.execute("SELECT COUNT(*) FROM provider_calls").fetchone()[0], 0)
                audit = service.db.connection.execute(
                    "SELECT metadata_json FROM audit_events WHERE event = 'skill_execution_succeeded'"
                ).fetchone()[0]
                self.assertNotIn("private local note", audit)
                self.assertIn("output_hash", audit)
            finally:
                service.close()

    def test_unapproved_metadata_only_and_invalid_skills_cannot_execute(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            service = MyLastAIGirlfriendsService(make_config(root))
            try:
                draft = service.create_skill("draft", "1.0.0", "local-test", ["read-only-file"], definition())
                with self.assertRaisesRegex(GovernanceError, "approved"):
                    service.execute_skill(draft["id"])
                service.transition_skill(draft["id"], "REVIEW")
                service.transition_skill(draft["id"], "APPROVED")
                service.transition_skill(draft["id"], "REVOKED")
                with self.assertRaisesRegex(GovernanceError, "approved"):
                    service.execute_skill(draft["id"])

                metadata_only = service.create_skill("metadata", "1.0.0", "local-test", ["read-only-text"])
                service.transition_skill(metadata_only["id"], "REVIEW")
                service.transition_skill(metadata_only["id"], "APPROVED")
                with self.assertRaisesRegex(GovernanceError, "no executable definition"):
                    service.execute_skill(metadata_only["id"])

                invalid = [
                    ({"schema_version": 1, "steps": []}, "exactly one"),
                    ({"schema_version": 1, "steps": [{"tool": "code.execute", "arguments": {}}]}, "local file-read"),
                    (definition("../notes.md"), "relative"),
                ]
                for manifest, message in invalid:
                    with self.assertRaisesRegex(GovernanceError, message):
                        service.create_skill("invalid", "1.0.0", "local-test", ["read-only-file"], manifest)
            finally:
                service.close()

    def test_missing_file_is_audited_without_returning_raw_content(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            service = MyLastAIGirlfriendsService(make_config(root))
            try:
                skill = approve(service, manifest=definition("missing.md"))
                with self.assertRaisesRegex(GovernanceError, "does not exist"):
                    service.execute_skill(skill["id"])
                row = service.db.connection.execute(
                    "SELECT metadata_json FROM audit_events WHERE event = 'skill_execution_failed'"
                ).fetchone()
                self.assertIsNotNone(row)
                self.assertIn("FILE_NOT_FOUND", row[0])
            finally:
                service.close()

    def test_authenticated_http_skill_run_is_strict_and_bounded(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            (root / "workspace" / "notes.md").write_text("http skill", encoding="utf-8")
            service = MyLastAIGirlfriendsService(make_config(root))
            skill = approve(service)
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            headers = {"Authorization": "Bearer " + "T" * 48, "Content-Type": "application/json"}
            try:
                connection.request("POST", f"/v1/skills/{skill['id']}/run", body="{}", headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()
                connection.request("POST", f"/v1/skills/{skill['id']}/run", body="{}", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["output"], "http skill")
                connection.request("POST", f"/v1/skills/{skill['id']}/run", body='{"path":"notes.md"}', headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 400)
                self.assertEqual(json.loads(response.read())["error"]["code"], "SKILL_RUN_BODY_INVALID")
                connection.request("POST", "/v1/skills/missing/run", body="{}", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 404)
                self.assertEqual(json.loads(response.read())["error"]["code"], "SKILL_NOT_FOUND")
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                service.close()


if __name__ == "__main__":
    unittest.main()
