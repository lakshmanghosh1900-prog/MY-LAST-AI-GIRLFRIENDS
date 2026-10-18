from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.connectors import ConnectorError, _NoRedirectHandler, call_mcp
from my_last_ai_girlfriends.governance import GovernanceError
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService

from test_budget_service import make_config


class Response:
    def __init__(self, payload, status=200):
        self.status = status
        self.payload = json.dumps(payload).encode()

    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self, _limit=-1): return self.payload

class TestOpener:
    def __init__(self, open_fn):
        self.open_fn = open_fn

    def open(self, request, timeout):
        return self.open_fn(request, timeout)


class ConnectorTests(unittest.TestCase):
    def test_mcp_transport_validates_json_rpc_and_returns_result(self):
        def opener(request, timeout):
            payload = json.loads(request.data.decode())
            self.assertEqual(payload["method"], "tools/list")
            self.assertEqual(timeout, 10)
            return Response({"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": []}})

        with patch("my_last_ai_girlfriends.connectors.urllib.request.build_opener", return_value=TestOpener(opener)) as build_opener:
            result = call_mcp("https://example.com/mcp", "tools/list", {})
        self.assertTrue(any(isinstance(handler, _NoRedirectHandler) for handler in build_opener.call_args.args))
        self.assertEqual(result["result"], {"tools": []})

    def test_mcp_transport_rejects_non_success_response_before_parsing(self):
        def opener(request, timeout):
            payload = json.loads(request.data.decode())
            return Response(
                {"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": []}},
                status=302,
            )

        with patch(
            "my_last_ai_girlfriends.connectors.urllib.request.build_opener",
            return_value=TestOpener(opener),
        ):
            with self.assertRaisesRegex(ConnectorError, "non-success HTTP status"):
                call_mcp("https://example.com/mcp", "tools/list", {})

    def test_redirect_handler_blocks_redirects(self):
        handler = _NoRedirectHandler()
        original = urllib.request.Request("https://example.com/mcp")
        redirected = handler.redirect_request(
            original,
            None,
            302,
            "Found",
            {},
            "https://127.0.0.1/admin",
        )
        self.assertIsNone(redirected)

    def test_service_requires_approved_read_scope(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            connector = service.register_connector("mcp", "https://example.com/mcp", "read:tools/list")
            with self.assertRaisesRegex(Exception, "approved"):
                service.invoke_connector(connector["id"], "tools/list", {})
            service.transition_connector(connector["id"], "APPROVED")
            with patch("my_last_ai_girlfriends.connectors.urllib.request.build_opener", return_value=TestOpener(lambda *_args, **_kwargs: Response({"jsonrpc": "2.0", "id": json.loads(_args[0].data.decode())["id"], "result": {"tools": []}}))):
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

        with patch("my_last_ai_girlfriends.connectors.urllib.request.build_opener", return_value=TestOpener(lambda *_args, **_kwargs: Response({"jsonrpc": "2.0", "id": json.loads(_args[0].data.decode())["id"], "result": []}))):
            with self.assertRaisesRegex(ConnectorError, "no result"):
                call_mcp("https://example.com/mcp", "tools/list", {})

    def test_service_rejects_private_connector_endpoint(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            with self.assertRaisesRegex(GovernanceError, "public HTTPS"):
                service.register_connector("local", "https://localhost/mcp", "read:tools/list")
            service.close()


if __name__ == "__main__":
    unittest.main()
