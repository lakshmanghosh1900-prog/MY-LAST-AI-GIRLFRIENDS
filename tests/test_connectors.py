from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.connectors import ConnectorError, call_mcp, _resolve_public
from my_last_ai_girlfriends.governance import GovernanceError
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService

from test_budget_service import make_config


class Response:
    def __init__(self, payload, status=200):
        self.status = status
        self.payload = json.dumps(payload).encode()
        self.closed = False
        self.read_called = False

    def read(self, limit=-1):
        self.read_called = True
        return self.payload if limit < 0 else self.payload[:limit]

    def close(self):
        self.closed = True


class FakeConnection:
    def __init__(self, status=200, result=None):
        self.status = status
        self.result = {"tools": []} if result is None else result
        self.request_args = None
        self.response = None
        self.closed = False

    def request(self, method, target, body, headers):
        payload = json.loads(body.decode("utf-8"))
        self.request_args = (method, target, payload, headers)
        self.response = Response(
            {"jsonrpc": "2.0", "id": payload["id"], "result": self.result},
            status=self.status,
        )

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


class ConnectorTests(unittest.TestCase):
    def test_mcp_transport_validates_json_rpc_and_returns_result(self):
        connection = FakeConnection()
        with patch("my_last_ai_girlfriends.connectors._resolve_public", return_value="93.184.216.34") as resolver, patch(
            "my_last_ai_girlfriends.connectors._PinnedHTTPSConnection", return_value=connection
        ) as factory:
            result = call_mcp("https://example.com/mcp", "tools/list", {})

        resolver.assert_called_once_with("example.com")
        factory.assert_called_once_with("example.com", "93.184.216.34", 10)
        self.assertEqual(result["result"], {"tools": []})
        self.assertEqual(connection.request_args[0], "POST")
        self.assertEqual(connection.request_args[1], "/mcp")
        self.assertEqual(connection.request_args[2]["method"], "tools/list")
        self.assertEqual(connection.request_args[3]["Host"], "example.com")
        self.assertTrue(connection.closed)
        self.assertTrue(connection.response.closed)

    def test_mcp_transport_rejects_non_success_response_before_parsing(self):
        connection = FakeConnection(status=302)
        with patch("my_last_ai_girlfriends.connectors._resolve_public", return_value="93.184.216.34"), patch(
            "my_last_ai_girlfriends.connectors._PinnedHTTPSConnection", return_value=connection
        ):
            with self.assertRaisesRegex(ConnectorError, "non-success HTTP status"):
                call_mcp("https://example.com/mcp", "tools/list", {})
        self.assertFalse(connection.response.read_called)
        self.assertTrue(connection.closed)

    def test_connector_dns_resolution_rejects_private_destinations(self):
        private_info = (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        with patch("my_last_ai_girlfriends.connectors.socket.getaddrinfo", return_value=[private_info]):
            with self.assertRaisesRegex(ConnectorError, "non-public address"):
                _resolve_public("mcp.example.com")

    def test_service_requires_approved_read_scope(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            connector = service.register_connector("mcp", "https://example.com/mcp", "read:tools/list")
            with self.assertRaisesRegex(Exception, "approved"):
                service.invoke_connector(connector["id"], "tools/list", {})
            service.transition_connector(connector["id"], "APPROVED")
            connection = FakeConnection()
            with patch("my_last_ai_girlfriends.connectors._resolve_public", return_value="93.184.216.34"), patch(
                "my_last_ai_girlfriends.connectors._PinnedHTTPSConnection", return_value=connection
            ):
                result = service.invoke_connector(connector["id"], "tools/list", {})
            self.assertEqual(result["result"]["result"], {"tools": []})
            service.close()

    def test_unsupported_mcp_method_is_rejected(self):
        with self.assertRaisesRegex(ConnectorError, "tools/list"):
            call_mcp("https://example.com/mcp", "resources/read", {})

    def test_mcp_rejects_private_endpoints_invalid_params_and_non_object_results(self):
        with self.assertRaisesRegex(ConnectorError, "public HTTPS"):
            call_mcp("https://127.0.0.1/mcp", "tools/list", {})
        with self.assertRaisesRegex(ConnectorError, "JSON data"):
            call_mcp("https://example.com/mcp", "tools/list", {"value": {1, 2}})

        connection = FakeConnection(result=[])
        with patch("my_last_ai_girlfriends.connectors._resolve_public", return_value="93.184.216.34"), patch(
            "my_last_ai_girlfriends.connectors._PinnedHTTPSConnection", return_value=connection
        ):
            with self.assertRaisesRegex(ConnectorError, "no result"):
                call_mcp("https://example.com/mcp", "tools/list", {})

    def test_connector_endpoints_reject_query_parameters(self):
        with self.assertRaisesRegex(ConnectorError, "query parameters"):
            call_mcp("https://example.com/mcp?access_token=secret", "tools/list", {})

    def test_service_rejects_private_connector_endpoint(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            with self.assertRaisesRegex(GovernanceError, "public HTTPS"):
                service.register_connector("local", "https://localhost/mcp", "read:tools/list")
            service.close()


if __name__ == "__main__":
    unittest.main()
