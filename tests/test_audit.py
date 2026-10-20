from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from my_last_ai_girlfriends.http_api import MyLastAIGirlfriendsHTTPServer
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService

from test_budget_service import make_config


class AuditTests(unittest.TestCase):
    def test_tool_execution_records_hashed_audit_without_storing_content(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            (root / "workspace" / "notes.txt").write_text("private checklist content", encoding="utf-8")
            service = MyLastAIGirlfriendsService(make_config(root))
            try:
                conversation = service.create_conversation()
                result = service.handle_message(conversation, "/file notes.txt")
                self.assertEqual(result.status, "SUCCEEDED")

                events = service.audit_events(50)
                executed = [item for item in events if item["event"] == "tool_executed"]
                self.assertEqual(len(executed), 1)
                metadata = executed[0]["metadata"]
                self.assertEqual(metadata["tool"], "file.read_text")
                self.assertEqual(len(metadata["arguments_hash"]), 64)
                self.assertGreater(metadata["result_bytes"], 0)
                self.assertEqual(metadata["data_class"], "SENSITIVE")
                serialized = json.dumps(events)
                self.assertNotIn("private checklist content", serialized)
                self.assertNotIn("notes.txt", serialized)
            finally:
                service.close()

    def test_rejected_and_failed_tool_calls_are_audited(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            service = MyLastAIGirlfriendsService(make_config(root))
            try:
                conversation = service.create_conversation()
                self.assertEqual(service.handle_message(conversation, "/file ").status, "SAFE_STOP")
                self.assertEqual(service.handle_message(conversation, "/file missing.txt").status, "SAFE_STOP")

                events = service.audit_events(50)
                rejected = [item for item in events if item["event"] == "tool_rejected"]
                failed = [item for item in events if item["event"] == "tool_failed"]
                self.assertEqual(len(rejected), 1)
                self.assertEqual(rejected[0]["metadata"]["decision"], "DENY")
                self.assertTrue(rejected[0]["metadata"]["code"])
                self.assertEqual(len(failed), 1)
                self.assertEqual(failed[0]["metadata"]["tool"], "file.read_text")
                self.assertEqual(failed[0]["metadata"]["code"], "FILE_NOT_FOUND")
                self.assertEqual(len(failed[0]["metadata"]["arguments_hash"]), 64)
            finally:
                service.close()

    def test_audit_readback_is_bounded_and_validated(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            try:
                self.assertIsInstance(service.audit_events(5), list)
                with self.assertRaises(ValueError):
                    service.audit_events(0)
                with self.assertRaises(ValueError):
                    service.audit_events(201)
                with self.assertRaises(ValueError):
                    service.audit_events(True)
                with self.assertRaises(ValueError):
                    service.audit_events(5, " ")
            finally:
                service.close()

    def test_audit_route_requires_auth_and_enforces_query_bounds(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            (root / "workspace" / "notes.txt").write_text("audit route content", encoding="utf-8")
            service = MyLastAIGirlfriendsService(make_config(root))
            conversation = service.create_conversation()
            service.handle_message(conversation, "/file notes.txt")
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
            headers = {"Authorization": "Bearer " + "T" * 48}
            try:
                connection.request("GET", "/v1/audit")
                response = connection.getresponse()
                response.read()
                self.assertEqual(response.status, 401)

                connection.request("GET", "/v1/audit?limit=200", headers=headers)
                response = connection.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200)
                events = payload["events"]
                self.assertTrue(events)
                self.assertLessEqual(len(events), 200)
                self.assertEqual({item["event"] for item in events if item["event"] == "tool_executed"}, {"tool_executed"})

                connection.request("GET", "/v1/audit?limit=1", headers=headers)
                response = connection.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertEqual(len(payload["events"]), 1)

                for bad in ("limit=0", "limit=201", "limit=abc", "limit=" + "9" * 20, "event=%20"):
                    connection.request("GET", f"/v1/audit?{bad}", headers=headers)
                    response = connection.getresponse()
                    response.read()
                    self.assertEqual(response.status, 400, bad)

                connection.request("GET", "/v1/audit?event=tool_executed&limit=50", headers=headers)
                response = connection.getresponse()
                payload = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["events"])
                self.assertEqual({item["event"] for item in payload["events"]}, {"tool_executed"})
                self.assertNotIn("audit route content", json.dumps(payload))
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                service.close()


if __name__ == "__main__":
    unittest.main()
