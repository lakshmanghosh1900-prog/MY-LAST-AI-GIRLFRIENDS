from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from jarvis_omega.auth import AuthManager
from jarvis_omega.http_api import JarvisHTTPServer
from jarvis_omega.service import JarvisService

from test_budget_service import make_config


class HttpApiTests(unittest.TestCase):
    def test_api_requires_bearer_and_rejects_bad_origin(self):
        with tempfile.TemporaryDirectory() as raw:
            service = JarvisService(make_config(Path(raw)))
            server = JarvisHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            try:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                connection.request("POST", "/v1/conversations", body="{}", headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()

                token = "T" * 48
                connection.request("POST", "/v1/conversations", body="{}", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Origin": "http://evil.example"})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()

                connection.request("POST", "/v1/conversations", body="{}", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Origin": f"http://127.0.0.1:{port}"})
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                payload = json.loads(response.read())
                self.assertIn("id", payload)
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                service.close()

    def test_auth_manager_does_not_accept_query_style_token(self):
        manager = AuthManager("T" * 64)
        self.assertFalse(manager.verify_bearer(None))
        self.assertFalse(manager.verify_bearer("Bearer " + "x" * 600))


if __name__ == "__main__":
    unittest.main()
