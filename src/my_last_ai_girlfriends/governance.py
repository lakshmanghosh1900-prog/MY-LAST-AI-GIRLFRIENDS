"""Local governance primitives for devices, connectors, skills and approvals.

These records deliberately do not execute external actions. They make the
approval and capability boundaries inspectable before any future integration is
enabled.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit


class GovernanceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


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


def validate_connector_endpoint(endpoint: str) -> str:
    parsed = urlsplit(endpoint.strip()) if isinstance(endpoint, str) else None
    if not parsed or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise GovernanceError("CONNECTOR_ENDPOINT_INVALID", "Connector endpoints must be credential-free HTTPS URLs.")
    if parsed.port not in {None, 443}:
        raise GovernanceError("CONNECTOR_PORT_INVALID", "Connector endpoints must use HTTPS port 443.")
    return endpoint.strip()


def new_nonce() -> str:
    return secrets.token_urlsafe(24)


@dataclass(frozen=True)
class ApprovalRequest:
    action_type: str
    parameters_json: str
    expires_at: str
