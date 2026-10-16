"""Deterministic policy decisions; the model cannot grant itself capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlsplit


class DataClass(StrEnum):
    PUBLIC = "PUBLIC"
    PERSONAL = "PERSONAL"
    SENSITIVE = "SENSITIVE"
    PROHIBITED = "PROHIBITED"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    SAFE_STOP = "SAFE_STOP"


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    code: str
    reason: str
    data_class: DataClass


class PolicyEngine:
    version = "policy-0.1.0"
    allowed_tools = frozenset({"file.read_text", "web.fetch"})

    def __init__(self, max_message_chars: int, allow_remote_personal_data: bool):
        self.max_message_chars = max_message_chars
        self.allow_remote_personal_data = allow_remote_personal_data

    def classify(self, message: str) -> DataClass:
        lower = message.lower()
        prohibited_markers = ("password", "api key", "apikey", "secret", "otp", "pin", "private key", "session cookie", "access token", "bearer token")
        sensitive_markers = ("health", "medical", "bank", "finance", "account number", "notification", "sms", "diagnosis", "prescription", "/file ")
        if any(marker in lower for marker in prohibited_markers):
            return DataClass.PROHIBITED
        if any(marker in lower for marker in sensitive_markers):
            return DataClass.SENSITIVE
        if lower.startswith("/fetch https://"):
            return DataClass.PUBLIC
        return DataClass.PERSONAL

    def check_message(self, message: str, provider: str, remote_consent: bool = False) -> PolicyDecision:
        if not message.strip():
            return PolicyDecision(Decision.DENY, "EMPTY_MESSAGE", "Message is empty.", DataClass.PERSONAL)
        if len(message) > self.max_message_chars:
            return PolicyDecision(Decision.DENY, "MESSAGE_TOO_LARGE", "Message exceeds the configured limit.", self.classify(message))
        data_class = self.classify(message)
        if data_class == DataClass.PROHIBITED:
            return PolicyDecision(Decision.DENY, "PROHIBITED_SECRET_DATA", "Credentials and authentication secrets are never sent to a model.", data_class)
        if provider == "gemini" and data_class == DataClass.SENSITIVE:
            return PolicyDecision(Decision.SAFE_STOP, "SENSITIVE_REMOTE_BLOCKED", "Sensitive content stays local and cannot be sent to the remote provider.", data_class)
        if provider == "gemini" and data_class == DataClass.PERSONAL and (not self.allow_remote_personal_data or not remote_consent):
            return PolicyDecision(Decision.SAFE_STOP, "REMOTE_CONSENT_REQUIRED", "Enable local remote-conversation consent before ordinary personal text can leave this device.", data_class)
        return PolicyDecision(Decision.ALLOW, "MESSAGE_ALLOWED", "Message is within the configured data policy.", data_class)

    def check_tool(self, name: str, arguments: dict) -> PolicyDecision:
        if name not in self.allowed_tools:
            return PolicyDecision(Decision.DENY, "TOOL_NOT_ALLOWLISTED", "The requested tool is not registered.", DataClass.PERSONAL)
        if not isinstance(arguments, dict):
            return PolicyDecision(Decision.DENY, "TOOL_ARGUMENTS_INVALID", "Tool arguments must be an object.", DataClass.PERSONAL)
        if name == "file.read_text":
            path = arguments.get("path")
            if not isinstance(path, str) or not path.strip():
                return PolicyDecision(Decision.DENY, "FILE_PATH_REQUIRED", "A relative file path is required.", DataClass.SENSITIVE)
            return PolicyDecision(Decision.ALLOW, "READ_ONLY_FILE_ALLOWED", "Read-only file access is allowlisted.", DataClass.SENSITIVE)
        if name == "web.fetch":
            url = arguments.get("url")
            if not isinstance(url, str):
                return PolicyDecision(Decision.DENY, "URL_REQUIRED", "An HTTPS URL is required.", DataClass.PUBLIC)
            parts = urlsplit(url)
            if parts.scheme != "https" or parts.username or parts.password or parts.port not in {None, 443}:
                return PolicyDecision(Decision.DENY, "UNSAFE_URL", "Only credential-free HTTPS URLs on port 443 are allowed.", DataClass.PUBLIC)
            return PolicyDecision(Decision.ALLOW, "PUBLIC_FETCH_ALLOWED", "Constrained public fetch is allowlisted.", DataClass.PUBLIC)
        return PolicyDecision(Decision.DENY, "TOOL_NOT_ALLOWLISTED", "The requested tool is not registered.", DataClass.PERSONAL)
