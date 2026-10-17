from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from my_last_ai_girlfriends.http_api import MyLastAIGirlfriendsHTTPServer
from my_last_ai_girlfriends.memory import MemoryError
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService
from my_last_ai_girlfriends.storage import Database

from test_budget_service import make_config


class MemoryTests(unittest.TestCase):
    def test_explicit_memory_is_persistent_scoped_and_deletable(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            service = MyLastAIGirlfriendsService(make_config(root))
            first = service.create_conversation()
            second = service.create_conversation()
            global_item = service.create_memory("I prefer concise answers.")
            local_item = service.create_memory("The first conversation is about Bengali practice.", "conversation", first)
            self.assertEqual({item["id"] for item in service.list_memories(first)}, {global_item["id"], local_item["id"]})
            self.assertEqual({item["id"] for item in service.list_memories(second)}, {global_item["id"]})
            with self.assertRaises(KeyError):
                service.delete_memory(local_item["id"], second)
            self.assertTrue(service.delete_memory(local_item["id"], first))
            service.close()

            reopened = MyLastAIGirlfriendsService(make_config(root))
            self.assertEqual([item["id"] for item in reopened.list_memories(first)], [global_item["id"]])
            reopened.close()

    def test_prohibited_and_sensitive_memory_are_not_persisted(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            with self.assertRaisesRegex(MemoryError, "Credentials"):
                service.create_memory("my password is never store this")
            with self.assertRaisesRegex(MemoryError, "Sensitive"):
                service.create_memory("my medical diagnosis")
            self.assertEqual(service.list_memories(), [])
            service.close()

    def test_expired_memory_is_not_listed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "memory.sqlite3")
            db.initialize()
            db.create_memory("global", None, "expired", "PERSONAL", "2000-01-01T00:00:00Z")
            self.assertEqual(db.list_memories(), [])
            self.assertEqual(db.connection.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0], 1)
            self.assertEqual(db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 7)
            db.close()

    def test_authenticated_http_memory_flow_and_isolation(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            token = "T" * 48
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request("GET", "/v1/memory")
                self.assertEqual(connection.getresponse().status, 401)
                conversation = service.create_conversation()
                body = json.dumps({"content": "Remember that I like Bengali books.", "scope": "conversation", "conversation_id": conversation})
                connection.request("POST", "/v1/memory", body=body, headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                item = json.loads(response.read())
                connection.request("GET", f"/v1/memory?conversation_id={conversation}", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["memories"][0]["id"], item["id"])
                connection.request("DELETE", f"/v1/memory/{item['id']}?conversation_id=wrong", headers=headers)
                self.assertEqual(connection.getresponse().status, 404)
                connection.request("DELETE", f"/v1/memory/{item['id']}?conversation_id={conversation}", headers=headers)
                self.assertEqual(connection.getresponse().status, 200)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                service.close()


if __name__ == "__main__":
    unittest.main()
