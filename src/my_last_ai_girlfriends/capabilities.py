"""Truthful capability inventory for the enabled release."""

from __future__ import annotations


def inventory() -> list[dict]:
    return [
        {"id": "android_companion", "status": "BLOCKED_EXTERNAL", "reason": "Android build/device verification is unavailable."},
        {"id": "device_pairing", "status": "PARTIAL", "reason": "Local enrollment, one-time replay-resistant challenges and diagnostics are enabled; encrypted transport is not."},
        {"id": "connector_registry", "status": "PARTIAL", "reason": "Approved credential-free read-only MCP JSON-RPC transport is enabled; write/external scopes are disabled."},
        {"id": "reviewed_skills", "status": "PARTIAL", "reason": "Approved declarative local file-read skills are enabled; shell, arbitrary code, network, provider and external side effects remain disabled."},
        {"id": "bounded_agents", "status": "PARTIAL", "reason": "Local bounded role pipeline exists; no remote delegation is enabled."},
        {"id": "human_approvals", "status": "PARTIAL", "reason": "Single-use approved local schedule execution is enabled; calendar/email side effects are disabled."},
        {"id": "offline_local_brain", "status": "FUNCTIONAL_MVP", "reason": "Truthful deterministic offline provider is enabled."},
        {"id": "ollama_local_brain", "status": "AVAILABLE_IF_CONFIGURED", "reason": "A loopback Ollama adapter is implemented; no local Ollama service was verified here."},
        {"id": "release_hardening", "status": "PARTIAL", "reason": "Deterministic checks exist; Docker/cleanup/main integration remain release gates."},
    ]
