"""Authenticated local HTTP API for the companion UI."""

from __future__ import annotations

import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .auth import AuthManager
from .documents import DocumentError
from .evaluation import run_local_evaluation
from .governance import GovernanceError, SkillNotFoundError
from .memory import MemoryError
from .orchestration import OrchestrationError
from .research import ResearchError
from .release import local_readiness
from .scheduler import SchedulerError
from .tool_registry import list_tools
from .redaction import redact
from .service import MyLastAIGirlfriendsService


INDEX_HTML = (Path(__file__).parent / "web" / "index.html").read_text(encoding="utf-8")


class MyLastAIGirlfriendsHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service: MyLastAIGirlfriendsService):
        self.service = service
        self.auth = AuthManager(service.config.auth_token_hash)
        super().__init__(address, MyLastAIGirlfriendsRequestHandler)


class MyLastAIGirlfriendsRequestHandler(BaseHTTPRequestHandler):
    server: MyLastAIGirlfriendsHTTPServer

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
        self._security_headers()
        self.send_header("X-Request-ID", request_id or self._request_id())
        self.end_headers()
        self.wfile.write(data)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")

    def _error(self, status: int, code: str, message: str, request_id: str) -> None:
        self._send(status, {"error": {"code": code, "message": message}}, request_id)

    def _host_ok(self) -> bool:
        host = self.headers.get("Host", "").lower()
        port = self.server.server_address[1]
        expected = {f"127.0.0.1:{port}", f"localhost:{port}", f"{self.server.service.config.host}:{port}"}
        if host in expected:
            return True
        if self.server.service.config.host != "127.0.0.1" and ":" in host:
            return host.rsplit(":", 1)[0] in self.server.service.config.trusted_hosts
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
        try:
            length = int(self.headers.get("Content-Length", "-1"))
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
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
            self._security_headers()
            self.end_headers()
            self.wfile.write(data)
            return
        if not self._authorized(request_id):
            return
        if path in {"/v1/health", "/v1/runtime"}:
            self._send(HTTPStatus.OK, self.server.service.runtime_info(), request_id)
            return
        if path == "/v1/tools":
            self._send(HTTPStatus.OK, {"tools": list_tools()}, request_id)
            return
        if path == "/v1/capabilities":
            self._send(HTTPStatus.OK, {"capabilities": self.server.service.capability_inventory()}, request_id)
            return
        if path == "/v1/readiness/local":
            self._send(HTTPStatus.OK, local_readiness(self.server.service.db), request_id)
            return
        if path == "/v1/evaluations/local":
            self._send(HTTPStatus.OK, run_local_evaluation(self.server.service).as_dict(), request_id)
            return
        if path == "/v1/devices":
            self._send(HTTPStatus.OK, {"devices": self.server.service.list_devices()}, request_id)
            return
        if path == "/v1/connectors":
            self._send(HTTPStatus.OK, {"connectors": self.server.service.list_connectors()}, request_id)
            return
        if path == "/v1/skills":
            self._send(HTTPStatus.OK, {"skills": self.server.service.list_skills()}, request_id)
            return
        if path == "/v1/approvals":
            self._send(HTTPStatus.OK, {"approvals": self.server.service.list_approvals()}, request_id)
            return
        if path == "/v1/agents/runs":
            self._send(HTTPStatus.OK, {"runs": self.server.service.list_agent_runs()}, request_id)
            return
        parts = [part for part in path.split("/") if part]
        if len(parts) == 4 and parts[:2] == ["v1", "devices"] and parts[3] == "diagnostics":
            try:
                self._send(HTTPStatus.OK, self.server.service.device_diagnostics(parts[2]), request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "DEVICE_NOT_FOUND", "Device does not exist.", request_id)
            return
        if path == "/v1/admin/budget":
            self._send(HTTPStatus.OK, self.server.service.budget_status(), request_id)
            return
        if path == "/v1/conversations":
            self._send(HTTPStatus.OK, {"conversations": self.server.service.list_conversations()}, request_id)
            return
        if path == "/v1/settings":
            self._send(HTTPStatus.OK, {"remote_conversation_consent": self.server.service.remote_consent_enabled()}, request_id)
            return
        if path == "/v1/memory":
            query = parse_qs(urlsplit(self.path).query)
            conversation_id = query.get("conversation_id", [None])[0]
            try:
                self._send(HTTPStatus.OK, {"memories": self.server.service.list_memories(conversation_id)}, request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND", "Conversation does not exist.", request_id)
            return
        if path == "/v1/documents":
            self._send(HTTPStatus.OK, {"documents": self.server.service.list_documents()}, request_id)
            return
        if path == "/v1/documents/search":
            query = parse_qs(urlsplit(self.path).query).get("q", [""])[0]
            try:
                self._send(HTTPStatus.OK, {"results": self.server.service.search_documents(query)}, request_id)
            except DocumentError as exc:
                self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code, str(exc), request_id)
            return
        parts = [part for part in path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["v1", "research"]:
            try:
                self._send(HTTPStatus.OK, self.server.service.research_run(parts[2]), request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "RESEARCH_NOT_FOUND", "Research run does not exist.", request_id)
            return
        if path == "/v1/schedules":
            query = parse_qs(urlsplit(self.path).query)
            conversation_id = query.get("conversation_id", [None])[0]
            try:
                self._send(HTTPStatus.OK, {"schedules": self.server.service.list_schedules(conversation_id)}, request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND", "Conversation does not exist.", request_id)
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
                self._send(HTTPStatus.CREATED, {"id": self.server.service.create_conversation()}, request_id)
                return
            if path == "/v1/settings/remote-consent":
                enabled = payload.get("enabled")
                if not isinstance(enabled, bool):
                    self._error(HTTPStatus.BAD_REQUEST, "ENABLED_REQUIRED", "enabled must be boolean.", request_id)
                    return
                self._send(HTTPStatus.OK, self.server.service.set_remote_consent(enabled), request_id)
                return
            if path == "/v1/memory/recall":
                query = payload.get("query")
                conversation_id = payload.get("conversation_id")
                if not isinstance(query, str):
                    self._error(HTTPStatus.BAD_REQUEST, "MEMORY_QUERY_REQUIRED", "query must be a string.", request_id)
                    return
                if conversation_id is not None and not isinstance(conversation_id, str):
                    self._error(HTTPStatus.BAD_REQUEST, "CONVERSATION_ID_INVALID", "conversation_id must be a string.", request_id)
                    return
                self._send(
                    HTTPStatus.OK,
                    {"memories": self.server.service.recall_memories(query, conversation_id)},
                    request_id,
                )
                return
            if path == "/v1/memory":
                content = payload.get("content")
                scope = payload.get("scope", "global")
                conversation_id = payload.get("conversation_id")
                expires_at = payload.get("expires_at")
                if not isinstance(content, str) or not isinstance(scope, str):
                    self._error(HTTPStatus.BAD_REQUEST, "MEMORY_FIELDS_INVALID", "content and scope are required strings.", request_id)
                    return
                if conversation_id is not None and not isinstance(conversation_id, str):
                    self._error(HTTPStatus.BAD_REQUEST, "CONVERSATION_ID_INVALID", "conversation_id must be a string.", request_id)
                    return
                if expires_at is not None and not isinstance(expires_at, str):
                    self._error(HTTPStatus.BAD_REQUEST, "MEMORY_EXPIRY_INVALID", "expires_at must be an ISO timestamp string.", request_id)
                    return
                result = self.server.service.create_memory(content, scope, conversation_id, expires_at)
                self._send(HTTPStatus.CREATED, result, request_id)
                return
            if path == "/v1/documents":
                relative_path = payload.get("path")
                if not isinstance(relative_path, str):
                    self._error(HTTPStatus.BAD_REQUEST, "DOCUMENT_PATH_REQUIRED", "path must be a string.", request_id)
                    return
                self._send(HTTPStatus.CREATED, self.server.service.index_document(relative_path), request_id)
                return
            if path == "/v1/documents/answer":
                query = payload.get("query")
                if not isinstance(query, str):
                    self._error(HTTPStatus.BAD_REQUEST, "DOCUMENT_QUERY_REQUIRED", "query must be a string.", request_id)
                    return
                self._send(HTTPStatus.OK, self.server.service.answer_documents(query), request_id)
                return
            if path == "/v1/research":
                urls = payload.get("urls")
                if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
                    self._error(HTTPStatus.BAD_REQUEST, "RESEARCH_URLS_INVALID", "urls must be a list of strings.", request_id)
                    return
                self._send(HTTPStatus.OK, self.server.service.run_research(urls), request_id)
                return
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["v1", "research"] and parts[3] == "evidence":
                claims = payload.get("claims")
                if not isinstance(claims, list) or not all(isinstance(claim, str) for claim in claims):
                    self._error(HTTPStatus.BAD_REQUEST, "RESEARCH_CLAIMS_INVALID", "claims must be a list of strings.", request_id)
                    return
                self._send(HTTPStatus.OK, self.server.service.analyze_research_evidence(parts[2], claims), request_id)
                return
            if path == "/v1/schedules":
                conversation_id = payload.get("conversation_id")
                title = payload.get("title")
                prompt = payload.get("prompt")
                run_at = payload.get("run_at")
                recurrence = payload.get("recurrence", "once")
                if not all(isinstance(value, str) for value in (conversation_id, title, prompt, run_at, recurrence)):
                    self._error(HTTPStatus.BAD_REQUEST, "SCHEDULE_FIELDS_INVALID", "conversation_id, title, prompt and run_at are required strings.", request_id)
                    return
                self._send(HTTPStatus.CREATED, self.server.service.create_schedule(conversation_id, title, prompt, run_at, recurrence), request_id)
                return
            if path == "/v1/schedules/run-due":
                now = payload.get("now")
                if now is not None and not isinstance(now, str):
                    self._error(HTTPStatus.BAD_REQUEST, "SCHEDULE_NOW_INVALID", "now must be an ISO timestamp string.", request_id)
                    return
                self._send(HTTPStatus.OK, {"runs": self.server.service.run_due_schedules(now)}, request_id)
                return
            if path == "/v1/devices":
                name, identity = payload.get("name"), payload.get("identity")
                if not isinstance(name, str) or not isinstance(identity, str):
                    self._error(HTTPStatus.BAD_REQUEST, "DEVICE_FIELDS_INVALID", "name and identity are required strings.", request_id)
                    return
                self._send(HTTPStatus.CREATED, self.server.service.enroll_device(name, identity), request_id)
                return
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["v1", "devices"] and parts[3] == "pairing-challenge":
                self._send(HTTPStatus.CREATED, self.server.service.create_device_pairing_challenge(parts[2]), request_id)
                return
            if len(parts) == 4 and parts[:2] == ["v1", "devices"] and parts[3] == "verify-pairing":
                challenge_id = payload.get("challenge_id")
                challenge = payload.get("challenge")
                identity = payload.get("identity")
                if not all(isinstance(value, str) for value in (challenge_id, challenge, identity)):
                    self._error(HTTPStatus.BAD_REQUEST, "PAIRING_FIELDS_INVALID", "challenge_id, challenge and identity are required strings.", request_id)
                    return
                self._send(
                    HTTPStatus.OK,
                    {"verified": self.server.service.verify_device_pairing_challenge(parts[2], challenge_id, challenge, identity)},
                    request_id,
                )
                return
            if len(parts) == 4 and parts[:2] == ["v1", "devices"] and parts[3] == "verify":
                identity = payload.get("identity")
                if not isinstance(identity, str):
                    self._error(HTTPStatus.BAD_REQUEST, "DEVICE_IDENTITY_INVALID", "identity is required.", request_id)
                    return
                self._send(HTTPStatus.OK, {"verified": self.server.service.verify_device(parts[2], identity)}, request_id)
                return
            if path == "/v1/connectors":
                name, endpoint, scope = payload.get("name"), payload.get("endpoint"), payload.get("scope")
                if not all(isinstance(value, str) for value in (name, endpoint, scope)):
                    self._error(HTTPStatus.BAD_REQUEST, "CONNECTOR_FIELDS_INVALID", "name, endpoint and scope are required strings.", request_id)
                    return
                self._send(HTTPStatus.CREATED, self.server.service.register_connector(name, endpoint, scope), request_id)
                return
            if len(parts) == 4 and parts[:2] == ["v1", "connectors"] and parts[3] == "call":
                method = payload.get("method")
                params = payload.get("params", {})
                if not isinstance(method, str) or not isinstance(params, dict):
                    self._error(HTTPStatus.BAD_REQUEST, "CONNECTOR_CALL_INVALID", "method and object params are required.", request_id)
                    return
                self._send(HTTPStatus.OK, self.server.service.invoke_connector(parts[2], method, params), request_id)
                return
            if path == "/v1/skills":
                values = [payload.get(key) for key in ("name", "version", "provenance")]
                if not all(isinstance(value, str) for value in values) or not isinstance(payload.get("capabilities"), list):
                    self._error(HTTPStatus.BAD_REQUEST, "SKILL_FIELDS_INVALID", "name, version, provenance and capabilities are required.", request_id)
                    return
                definition = payload.get("definition")
                if definition is not None and not isinstance(definition, dict):
                    self._error(HTTPStatus.BAD_REQUEST, "SKILL_DEFINITION_INVALID", "definition must be an object when provided.", request_id)
                    return
                self._send(HTTPStatus.CREATED, self.server.service.create_skill(*values, payload["capabilities"], definition), request_id)
                return
            if path == "/v1/approvals":
                action_type, parameters, expires_at = payload.get("action_type"), payload.get("parameters"), payload.get("expires_at")
                if not isinstance(action_type, str) or not isinstance(parameters, dict) or not isinstance(expires_at, str):
                    self._error(HTTPStatus.BAD_REQUEST, "APPROVAL_FIELDS_INVALID", "action_type, parameters and expires_at are required.", request_id)
                    return
                self._send(HTTPStatus.CREATED, self.server.service.create_approval(action_type, parameters, expires_at), request_id)
                return
            if len(parts) == 4 and parts[:2] == ["v1", "approvals"] and parts[3] == "execute":
                parameters = payload.get("parameters")
                nonce = payload.get("nonce")
                if not isinstance(parameters, dict) or not isinstance(nonce, str):
                    self._error(HTTPStatus.BAD_REQUEST, "APPROVAL_PROOF_INVALID", "parameters and nonce are required.", request_id)
                    return
                self._send(HTTPStatus.OK, self.server.service.execute_approved_action(parts[2], parameters, nonce), request_id)
                return
            if path == "/v1/agents/run":
                prompt = payload.get("prompt")
                if not isinstance(prompt, str):
                    self._error(HTTPStatus.BAD_REQUEST, "AGENT_PROMPT_REQUIRED", "prompt is required.", request_id)
                    return
                self._send(HTTPStatus.OK, self.server.service.run_agents(prompt), request_id)
                return
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[0:2] == ["v1", "connectors"] and parts[3] == "status":
                status = payload.get("status")
                if not isinstance(status, str):
                    self._error(HTTPStatus.BAD_REQUEST, "STATUS_REQUIRED", "status is required.", request_id)
                    return
                self._send(HTTPStatus.OK, {"updated": self.server.service.transition_connector(parts[2], status)}, request_id)
                return
            if len(parts) == 4 and parts[0:2] == ["v1", "skills"] and parts[3] == "status":
                status = payload.get("status")
                if not isinstance(status, str):
                    self._error(HTTPStatus.BAD_REQUEST, "STATUS_REQUIRED", "status is required.", request_id)
                    return
                self._send(HTTPStatus.OK, {"updated": self.server.service.transition_skill(parts[2], status)}, request_id)
                return
            if len(parts) == 4 and parts[0:2] == ["v1", "skills"] and parts[3] == "run":
                if payload:
                    self._error(HTTPStatus.BAD_REQUEST, "SKILL_RUN_BODY_INVALID", "Skill execution does not accept runtime arguments.", request_id)
                    return
                self._send(HTTPStatus.OK, self.server.service.execute_skill(parts[2]), request_id)
                return
            if len(parts) == 4 and parts[0:2] == ["v1", "approvals"] and parts[3] == "status":
                status = payload.get("status")
                session = payload.get("approver_session")
                if not isinstance(status, str) or (session is not None and not isinstance(session, str)):
                    self._error(HTTPStatus.BAD_REQUEST, "APPROVAL_STATUS_INVALID", "status is required and session must be a string.", request_id)
                    return
                self._send(HTTPStatus.OK, {"updated": self.server.service.transition_approval(parts[2], status, session)}, request_id)
                return
            parts = [part for part in path.split("/") if part]
            if len(parts) == 4 and parts[:2] == ["v1", "conversations"] and parts[3] == "messages":
                content = payload.get("content")
                if not isinstance(content, str):
                    self._error(HTTPStatus.BAD_REQUEST, "CONTENT_REQUIRED", "content must be a string.", request_id)
                    return
                memory_ids = payload.get("memory_ids")
                if memory_ids is not None and (not isinstance(memory_ids, list) or not all(isinstance(item, str) for item in memory_ids)):
                    self._error(HTTPStatus.BAD_REQUEST, "MEMORY_SELECTION_INVALID", "memory_ids must be a list of strings.", request_id)
                    return
                result = self.server.service.handle_message(parts[2], content, memory_ids)
                status = HTTPStatus.OK if result.status == "SUCCEEDED" else HTTPStatus.UNPROCESSABLE_ENTITY
                self._send(status, result.as_dict(), request_id)
                return
            if path == "/v1/admin/stop":
                self._send(HTTPStatus.OK, {"state": self.server.service.stop()}, request_id)
                return
            if path == "/v1/admin/start":
                self._send(HTTPStatus.OK, {"state": self.server.service.start()}, request_id)
                return
        except SkillNotFoundError as exc:
            self._error(HTTPStatus.NOT_FOUND, exc.code, str(exc), request_id)
            return
        except KeyError:
            self._error(HTTPStatus.NOT_FOUND, "CONVERSATION_NOT_FOUND", "Conversation does not exist.", request_id)
            return
        except MemoryError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code, str(exc), request_id)
            return
        except DocumentError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code, str(exc), request_id)
            return
        except ResearchError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code, str(exc), request_id)
            return
        except SchedulerError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code, str(exc), request_id)
            return
        except GovernanceError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code, str(exc), request_id)
            return
        except OrchestrationError as exc:
            self._error(HTTPStatus.UNPROCESSABLE_ENTITY, exc.code, str(exc), request_id)
            return
        except ConnectorError as exc:
            self._error(HTTPStatus.BAD_GATEWAY, exc.code, str(exc), request_id)
            return
        except RuntimeError as exc:
            self._error(HTTPStatus.SERVICE_UNAVAILABLE, "SERVICE_NOT_READY", str(exc), request_id)
            return
        self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.", request_id)

    def do_DELETE(self) -> None:
        request_id = self._request_id()
        if not self._authorized(request_id):
            return
        parsed = urlsplit(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) == 3 and parts[:2] == ["v1", "memory"]:
            query = parse_qs(parsed.query)
            conversation_id = query.get("conversation_id", [None])[0]
            try:
                deleted = self.server.service.delete_memory(parts[2], conversation_id)
                self._send(HTTPStatus.OK, {"deleted": deleted}, request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "MEMORY_NOT_FOUND", "Memory does not exist.", request_id)
            return
        if len(parts) == 3 and parts[:2] == ["v1", "documents"]:
            try:
                self._send(HTTPStatus.OK, {"deleted": self.server.service.delete_document(parts[2])}, request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "DOCUMENT_NOT_FOUND", "Document does not exist.", request_id)
            return
        if len(parts) == 3 and parts[:2] == ["v1", "schedules"]:
            try:
                self._send(HTTPStatus.OK, {"cancelled": self.server.service.cancel_schedule(parts[2])}, request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "SCHEDULE_NOT_FOUND", "Schedule does not exist.", request_id)
            return
        if len(parts) == 4 and parts[:2] == ["v1", "devices"] and parts[3] == "revoke":
            try:
                self._send(HTTPStatus.OK, {"revoked": self.server.service.revoke_device(parts[2])}, request_id)
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "DEVICE_NOT_FOUND", "Device does not exist.", request_id)
            return
        self._error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "Route not found.", request_id)
