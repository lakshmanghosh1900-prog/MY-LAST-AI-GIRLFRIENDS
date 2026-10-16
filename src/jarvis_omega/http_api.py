"""Minimal authenticated HTTP API and browser client."""

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from .auth import AuthManager
from .redaction import redact
from .service import JarvisService


INDEX_HTML = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")


class JarvisHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service: JarvisService):
        self.service = service
        self.auth = AuthManager(service.config.auth_token_hash)
        super().__init__(address, JarvisRequestHandler)


class JarvisRequestHandler(BaseHTTPRequestHandler):
    server: JarvisHTTPServer

    def log_message(self, format: str, *args) -> None:
        self.server.service.db.add_audit("http", {"message": redact(format % args)})

    def _request_id(self) -> str:
        return secrets.token_hex(12)

    def _send(self, status: int, payload, request_id: str | None = None) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Request-ID", request_id or self._request_id())
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, code: str, message: str, request_id: str) -> None:
        self._send(status, {"error": {"code": code, "message": message}}, request_id)

    def _host_ok(self) -> bool:
        expected = f"{self.server.service.config.host}:{self.server.server_address[1]}"
        host = self.headers.get("Host", "").lower()
        port = self.server.server_address[1]
        if host in {expected, f"127.0.0.1:{port}", f"localhost:{port}"}:
            return True
        if self.server.service.config.host != "127.0.0.1" and ":" in host:
            host_without_port = host.rsplit(":", 1)[0]
            return host_without_port in self.server.service.config.trusted_hosts
        return host in self.server.service.config.trusted_hosts

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]
        return origin in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}

    def _authorized(self, request_id: str) -> bool:
        if not self._host_ok():
            self._error(HTTPStatus.BAD_REQUEST, "HOST_REJECTED", "Unexpected host header.", request_id)
            return False
        if not self._origin_ok():
            self._error(HTTPStatus.FORBIDDEN, "ORIGIN_REJECTED", "Unexpected browser origin.", request_id)
            return False
        if not self.server.auth.verify_bearer(self.headers.get("Authorization")):
            self._error(HTTPStatus.UNAUTHORIZED, "AUTH_REQUIRED", "Use an Authorization: Bearer token.", request_id)
            return False
        return True

    def _json_body(self, request_id: str) -> dict | None:
        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or "-1")
        except ValueError:
            self._error(HTTPStatus.BAD_REQUEST, "CONTENT_LENGTH_INVALID", "Content-Length is invalid.", request_id)
            return None
        if length < 0 or length > 65536:
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "BODY_TOO_LARGE", "Request body is too large.", request_id)
            return None
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(HTTPStatus.BAD_REQUEST, "JSON_INVALID", "Request body must be valid JSON.", request_id)
            return None
        if not isinstance(payload, dict):
            self._error(HTTPStatus.BAD_REQUEST, "JSON_OBJECT_REQUIRED", "Request body must be an object.", request_id)
            return None
        return payload

    def do_GET(self) -> None:
        request_id = self._request_id()
        path = urlsplit(self.path).path
        if path == "/":
            data = INDEX_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'none'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)
            return
        if not self._authorized(request_id):
            return
        if path in {"/health", "/v1/health"}:
            self._send(HTTPStatus.OK, self.server.service.health(), request_id)
            return
        if path == "/v1/admin/budget":
            self._send(HTTPStatus.OK, self.server.service.budget_status(), request_id)
            return
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[0] == "v1" and parts[1] == "conversations":
            try:
                self._send(HTTPStatus.OK, self.server.service.conversation(parts[2]), request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND", "Conversation does not exist.", request_id)
            return
        self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.", request_id)

    def do_POST(self) -> None:
        request_id = self._request_id()
        if not self._authorized(request_id):
            return
        path = urlsplit(self.path).path
        payload = self._json_body(request_id)
        if payload is None:
            return
        try:
            if path == "/v1/conversations":
                conversation_id = self.server.service.create_conversation()
                self._send(HTTPStatus.CREATED, {"id": conversation_id}, request_id)
                return
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["v1", "conversations"] and parts[3] == "messages":
                content = payload.get("content")
                if not isinstance(content, str):
                    self._error(HTTPStatus.BAD_REQUEST, "CONTENT_REQUIRED", "content must be a string.", request_id)
                    return
                result = self.server.service.handle_message(parts[2], content)
                status = HTTPStatus.OK if result.status == "SUCCEEDED" else HTTPStatus.UNPROCESSABLE_ENTITY
                self._send(status, result.as_dict(), request_id)
                return
            if path == "/v1/admin/stop":
                self._send(HTTPStatus.OK, {"state": self.server.service.stop()}, request_id)
                return
            if path == "/v1/admin/start":
                self._send(HTTPStatus.OK, {"state": self.server.service.start()}, request_id)
                return
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND", "Conversation does not exist.", request_id)
            return
        except RuntimeError as exc:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "SERVICE_NOT_READY", str(exc), request_id)
            return
        self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.", request_id)
