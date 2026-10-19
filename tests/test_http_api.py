from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from my_last_ai_girlfriends.auth import AuthManager
from my_last_ai_girlfriends.http_api import MyLastAIGirlfriendsHTTPServer, MyLastAIGirlfriendsRequestHandler
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService

from test_budget_service import make_config


class HttpApiTests(unittest.TestCase):
    def test_api_requires_bearer_and_rejects_bad_origin(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
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
                listing = connection.request("GET", "/v1/conversations", headers={"Authorization": f"Bearer {token}"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())["conversations"])
                connection.close()
            finally:
                server.shutdown()
                server.server_close()
                service.close()

    def test_request_path_rejects_malformed_authority_as_controlled_400(self):
        handler = object.__new__(MyLastAIGirlfriendsRequestHandler)
        handler.path = "//[malformed"
        errors = []
        handler._error = lambda *args: errors.append(args)

        self.assertIsNone(handler._request_path("request-1"))
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0][0], 400)
        self.assertEqual(errors[0][1], "REQUEST_TARGET_INVALID")

    def test_request_path_extracts_normal_origin_form_path(self):
        handler = object.__new__(MyLastAIGirlfriendsRequestHandler)
        handler.path = "/v1/health?safe=1"
        self.assertEqual(handler._request_path("request-2"), "/v1/health")

    def test_auth_manager_does_not_accept_query_style_token(self):
        manager = AuthManager("T" * 64)
        self.assertFalse(manager.verify_bearer(None))
        self.assertFalse(manager.verify_bearer("Bearer " + "x" * 600))

    def test_ui_and_api_emit_browser_security_headers(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                connection.request("GET", "/")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                csp = response.getheader("Content-Security-Policy", "")
                self.assertIn("object-src 'none'", csp)
                self.assertIn("base-uri 'none'", csp)
                self.assertIn("frame-ancestors 'none'", csp)
                self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
                self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
                self.assertEqual(response.getheader("Cross-Origin-Resource-Policy"), "same-origin")
                self.assertEqual(response.getheader("Permissions-Policy"), "camera=(), microphone=(self), geolocation=()")
                response.read()

                token = "T" * 48
                connection.request("GET", "/v1/conversations", headers={"Authorization": f"Bearer {token}"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
                self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
                self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
                response.read()
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                service.close()

    def test_remote_consent_is_explicit_and_readable(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            token = "T" * 48
            try:
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
                connection.request("GET", "/v1/settings", headers=headers)
                response = connection.getresponse()
                self.assertFalse(json.loads(response.read())["remote_conversation_consent"])
                connection.request("POST", "/v1/settings/remote-consent", body='{"enabled":true}', headers=headers)
                response = connection.getresponse()
                self.assertTrue(json.loads(response.read())["remote_conversation_consent"])
            finally:
                server.shutdown()
                server.server_close()
                service.close()

    def test_manual_due_schedule_route_is_authenticated_and_runs_due_work(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            conversation = service.create_conversation()
            schedule = service.create_schedule(conversation, "Run me", "manual scheduled hello", "2020-01-01T00:00:00Z")
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            port = server.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            headers = {"Authorization": "Bearer " + "T" * 48, "Content-Type": "application/json"}
            try:
                connection.request("POST", "/v1/schedules/run-due", body="{}", headers={"Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()

                connection.request(
                    "POST",
                    "/v1/schedules/run-due",
                    body=json.dumps({"now": "2025-01-01T00:00:00Z"}),
                    headers=headers,
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read())
                self.assertEqual(payload["runs"][0]["schedule_id"], schedule["id"])
                self.assertEqual(payload["runs"][0]["status"], "SUCCEEDED")
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                service.close()

    def test_capability_readiness_and_governance_routes_are_authenticated(self):
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
                connection.request("GET", "/v1/capabilities", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                capabilities = json.loads(response.read())["capabilities"]
                self.assertIn("device_pairing", {item["id"] for item in capabilities})
                skill_capability = next(item for item in capabilities if item["id"] == "reviewed_skills")
                self.assertIn("declarative local file-read", skill_capability["reason"])

                connection.request("GET", "/v1/readiness/local", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())["ready_for_local_tests"])

                connection.request("POST", "/v1/devices", body=json.dumps({"name": "phone", "identity": "proof"}), headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                device_id = json.loads(response.read())["id"]
                connection.request("POST", f"/v1/devices/{device_id}/pairing-challenge", body="{}", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                challenge = json.loads(response.read())
                connection.request(
                    "POST",
                    f"/v1/devices/{device_id}/verify-pairing",
                    body=json.dumps({"challenge_id": challenge["id"], "challenge": challenge["challenge"], "identity": "proof"}),
                    headers=headers,
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertTrue(json.loads(response.read())["verified"])

                connection.request("POST", "/v1/agents/run", body=json.dumps({"prompt": "local plan"}), headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                run_id = json.loads(response.read())["run_id"]
                connection.request("GET", "/v1/agents/runs", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["runs"][0]["id"], run_id)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                service.close()


if __name__ == "__main__":
    unittest.main()
