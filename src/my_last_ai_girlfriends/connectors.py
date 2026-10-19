"""Bounded, credential-free MCP JSON-RPC transport for approved read scopes.

Connector sockets are pinned to a resolved public IP address. This avoids
following redirects and prevents DNS rebinding between validation and connect.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import socket
import ssl
import uuid
from urllib.parse import urlsplit, urlunsplit

from .governance import GovernanceError, validate_connector_endpoint


class ConnectorError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _resolve_public(host: str) -> str:
    """Resolve a host once, rejecting any private or special-use address."""

    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ConnectorError("MCP_DNS_LOOKUP_FAILED", "The connector host could not be resolved.") from exc

    addresses: list[str] = []
    for info in infos:
        try:
            address = ipaddress.ip_address(info[4][0])
        except (IndexError, ValueError) as exc:
            raise ConnectorError("MCP_DNS_ADDRESS_INVALID", "The connector resolved to an invalid address.") from exc
        if not address.is_global:
            raise ConnectorError("MCP_PRIVATE_ENDPOINT", "The connector host resolves to a non-public address.")
        normalized = str(address)
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise ConnectorError("MCP_DNS_LOOKUP_FAILED", "The connector host has no usable address.")
    return addresses[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that uses a prevalidated IP while preserving TLS identity."""

    def __init__(self, host: str, resolved_ip: str, timeout_seconds: int):
        super().__init__(host=host, port=443, timeout=timeout_seconds, context=ssl.create_default_context())
        self._resolved_ip = resolved_ip

    def connect(self) -> None:  # pragma: no cover - exercised by transport integration tests
        raw = socket.create_connection((self._resolved_ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


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
        serialized_params = json.dumps(params, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ConnectorError("MCP_PARAMS_INVALID", "MCP parameters must be JSON data.") from exc
    if not isinstance(params, dict) or len(serialized_params) > 32_000:
        raise ConnectorError("MCP_PARAMS_INVALID", "MCP parameters must be a bounded JSON object.")

    request_id = str(uuid.uuid4())
    body = json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        separators=(",", ":"),
    ).encode("utf-8")
    parsed = urlsplit(endpoint)
    host = parsed.hostname or ""
    target = urlunsplit(("", "", parsed.path or "/", "", ""))
    resolved_ip = _resolve_public(host)
    connection = _PinnedHTTPSConnection(host, resolved_ip, timeout_seconds)
    try:
        connection.request(
            "POST",
            target,
            body=body,
            headers={
                "Host": parsed.netloc,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "my-last-ai-girlfriends/0.2.0",
                "Connection": "close",
            },
        )
        response = connection.getresponse()
        try:
            if response.status != 200:
                raise ConnectorError("MCP_HTTP_ERROR", "The connector returned a non-success HTTP status.")
            raw = response.read(max_bytes + 1)
        finally:
            response.close()
    except ConnectorError:
        raise
    except (http.client.HTTPException, ssl.SSLError, socket.timeout, TimeoutError, OSError) as exc:
        raise ConnectorError("MCP_TRANSPORT_ERROR", "The connector did not return a completed response.") from exc
    finally:
        connection.close()

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
