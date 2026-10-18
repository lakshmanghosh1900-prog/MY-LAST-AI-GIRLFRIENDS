"""Local governance primitives for devices, connectors, skills and approvals.

These records deliberately do not execute external actions. They make the
approval and capability boundaries inspectable before any future integration is
enabled.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit


class GovernanceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SkillNotFoundError(GovernanceError):
    """A requested skill does not exist; kept distinct for the HTTP 404 path."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_approval_expiry(value: str) -> datetime:
    """Parse an ISO approval expiry and normalize it to timezone-aware UTC."""

    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise GovernanceError("APPROVAL_EXPIRY_INVALID", "Approval expiry must be a valid ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise GovernanceError("APPROVAL_EXPIRY_INVALID", "Approval expiry must be a valid ISO timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GovernanceError("APPROVAL_EXPIRY_TIMEZONE_REQUIRED", "Approval expiry must include a timezone.")
    return parsed.astimezone(timezone.utc)


def secret_hash(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise GovernanceError("SECRET_REQUIRED", "A non-empty secret value is required.")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: dict) -> str:
    if not isinstance(value, dict):
        raise GovernanceError("PARAMETERS_INVALID", "Action parameters must be an object.")
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise GovernanceError("PARAMETERS_INVALID", "Action parameters must be JSON data.") from exc


def validate_skill_definition(definition: dict, capabilities: list[str]) -> dict:
    """Validate the only executable skill form currently enabled.

    Skill execution is deliberately declarative and narrower than the global
    tool registry: one approved local text-file read, with no substitutions,
    expressions, network access, provider calls or side effects.
    """

    if not isinstance(definition, dict) or set(definition) != {"schema_version", "steps"}:
        raise GovernanceError("SKILL_DEFINITION_INVALID", "Skill definition must contain only schema_version and steps.")
    if definition.get("schema_version") != 1 or isinstance(definition.get("schema_version"), bool):
        raise GovernanceError("SKILL_DEFINITION_VERSION_UNSUPPORTED", "Only skill definition schema version 1 is supported.")
    if not isinstance(capabilities, list) or set(capabilities) != {"read-only-file"} or len(capabilities) != 1:
        raise GovernanceError("SKILL_CAPABILITY_REJECTED", "Executable skills require exactly the read-only-file capability.")
    steps = definition.get("steps")
    if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], dict):
        raise GovernanceError("SKILL_DEFINITION_INVALID", "A skill must contain exactly one declarative step.")
    step = steps[0]
    if set(step) != {"tool", "arguments"} or step.get("tool") != "file.read_text":
        raise GovernanceError("SKILL_TOOL_DISABLED", "Only the approved local file-read tool can execute in a skill.")
    arguments = step.get("arguments")
    if not isinstance(arguments, dict) or set(arguments) != {"path"}:
        raise GovernanceError("SKILL_ARGUMENTS_INVALID", "The file-read step requires exactly one path argument.")
    path = arguments.get("path")
    normalized = path.replace("\\", "/") if isinstance(path, str) else ""
    parts = normalized.split("/") if normalized else []
    if (
        not isinstance(path, str)
        or not normalized.strip()
        or len(normalized) > 512
        or "\x00" in path
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in parts)
        or any(part.startswith(".") for part in parts)
        or ":" in normalized
    ):
        raise GovernanceError("SKILL_PATH_INVALID", "Skill paths must be clean, relative, visible text-file paths.")
    return {"schema_version": 1, "steps": [{"tool": "file.read_text", "arguments": {"path": normalized}}]}


def validate_connector_endpoint(endpoint: str) -> str:
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise GovernanceError("CONNECTOR_ENDPOINT_INVALID", "Connector endpoints must be credential-free HTTPS URLs.")
    try:
        parsed = urlsplit(endpoint.strip())
    except ValueError as exc:
        raise GovernanceError("CONNECTOR_ENDPOINT_INVALID", "Connector endpoint URL syntax is invalid.") from exc
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise GovernanceError("CONNECTOR_ENDPOINT_INVALID", "Connector endpoints must be credential-free HTTPS URLs.")
    if parsed.query:
        raise GovernanceError(
            "CONNECTOR_QUERY_UNSUPPORTED",
            "Connector endpoints must not include query parameters that could carry credentials.",
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise GovernanceError("CONNECTOR_PORT_INVALID", "Connector endpoints must use HTTPS port 443.") from exc
    if port not in {None, 443}:
        raise GovernanceError("CONNECTOR_PORT_INVALID", "Connector endpoints must use HTTPS port 443.")
    host = (parsed.hostname or "").casefold().rstrip(".")
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".localhost")):
        raise GovernanceError("CONNECTOR_PRIVATE_ENDPOINT", "Connector endpoints must use public HTTPS hosts.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise GovernanceError("CONNECTOR_PRIVATE_ENDPOINT", "Connector endpoints must use public HTTPS addresses.")
    return endpoint.strip()


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


@dataclass(frozen=True)
class ApprovalRequest:
    action_type: str
    parameters_json: str
    expires_at: str
