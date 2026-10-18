"""Bounded, credential-free MCP JSON-RPC transport for approved read scopes."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid

from .governance import GovernanceError, validate_connector_endpoint


class ConnectorError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Block redirects so a public MCP URL cannot redirect into a private endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def call_mcp(endpoint: str, method: str, params: dict, timeout_seconds: int = 10, max_bytes: int = 262_144) -> dict:
    try:
        endpoint = validate_connector_endpoint(endpoint)
    except GovernanceError as exc:
        raise ConnectorError(exc.code, str(exc)) from exc
    if method not in {"tools/list", "tools/call"}:
        raise ConnectorError("MCP_METHOD_UNSUPPORTED", "Only MCP tools/list and tools/call are supported.")
    if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 60:
        raise ConnectorError("MCP_TIMEOUT_INVALID", "The connector timeout must be between 1 and 60 seconds.")
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or not 1024 <= max_bytes <= 1_048_576:
        raise ConnectorError("MCP_RESPONSE_LIMIT_INVALID", "The connector response limit is invalid.")
    try:
        serialized_params = json.dumps(params, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ConnectorError("MCP_PARAMS_INVALID", "MCP parameters must be JSON data.") from exc
    if not isinstance(params, dict) or len(serialized_params) > 32_000:
        raise ConnectorError("MCP_PARAMS_INVALID", "MCP parameters must be a bounded JSON object.")
    request_id = str(uuid.uuid4())
    body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(endpoint, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "my-last-ai-girlfriends/0.2.0"})
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=timeout_seconds) as response:
            raw = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise ConnectorError("MCP_HTTP_ERROR", "The connector returned an HTTP error.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectorError("MCP_TRANSPORT_ERROR", "The connector did not return a completed response.") from exc
    if len(raw) > max_bytes:
        raise ConnectorError("MCP_RESPONSE_TOO_LARGE", "The connector response exceeded the configured limit.")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConnectorError("MCP_RESPONSE_INVALID", "The connector returned invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or payload.get("id") != request_id:
        raise ConnectorError("MCP_RESPONSE_INVALID", "The connector returned an invalid JSON-RPC response.")
    if "error" in payload:
        raise ConnectorError("MCP_REMOTE_ERROR", "The connector reported an MCP error.")
    if "result" not in payload or not isinstance(payload["result"], dict):
        raise ConnectorError("MCP_RESPONSE_INVALID", "The connector response has no result.")
    return {"method": method, "request_id": request_id, "result": payload["result"]}
