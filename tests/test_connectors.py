from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.connectors import ConnectorError, call_mcp
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService

from test_budget_service import make_config


class Response:
    status = 200

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def read(self, _limit=-1): return self.payload


class ConnectorTests(unittest.TestCase):
    def test_mcp_transport_validates_json_rpc_and_returns_result(self):
        def opener(request, timeout):
            payload = json.loads(request.data.decode())
            self.assertEqual(payload["method"], "tools/list")
            self.assertEqual(timeout, 10)
            return Response({"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": []}})

        with patch("urllib.request.urlopen", opener):
            result = call_mcp("https://example.com/mcp", "tools/list", {})
        self.assertEqual(result["result"], {"tools": []})

    def test_service_requires_approved_read_scope(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            connector = service.register_connector("mcp", "https://example.com/mcp", "read:tools/list")
            with self.assertRaisesRegex(Exception, "approved"):
                service.invoke_connector(connector["id"], "tools/list", {})
            service.transition_connector(connector["id"], "APPROVED")
            with patch("my_last_ai_girlfriends.connectors.urllib.request.urlopen", lambda *_args, **_kwargs: Response({"jsonrpc": "2.0", "id": json.loads(_args[0].data.decode())["id"], "result": {"tools": []}})):
                result = service.invoke_connector(connector["id"], "tools/list", {})
            self.assertEqual(result["result"]["result"], {"tools": []})
            service.close()

    def test_unsupported_mcp_method_is_rejected(self):
        with self.assertRaisesRegex(ConnectorError, "tools/list"):
            call_mcp("https://example.com/mcp", "resources/read", {})


if __name__ == "__main__":
    unittest.main()
