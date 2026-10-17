"""Truthful capability inventory for the enabled release."""

from __future__ import annotations


def inventory() -> list[dict]:
    return [
        {"id": "android_companion", "status": "BLOCKED_EXTERNAL", "reason": "Android build/device verification is unavailable."},
        {"id": "device_pairing", "status": "PARTIAL", "reason": "Local enrollment and revocation are enabled; encrypted transport is not."},
        {"id": "connector_registry", "status": "PARTIAL", "reason": "Draft/approval registry exists; no connector execution is enabled."},
        {"id": "reviewed_skills", "status": "PARTIAL", "reason": "Review lifecycle exists; skill code execution is disabled."},
        {"id": "bounded_agents", "status": "PARTIAL", "reason": "Local bounded role pipeline exists; no remote delegation is enabled."},
        {"id": "human_approvals", "status": "PARTIAL", "reason": "Approval records exist; external action execution is disabled."},
        {"id": "offline_local_brain", "status": "FUNCTIONAL_MVP", "reason": "Truthful deterministic offline provider is enabled."},
        {"id": "release_hardening", "status": "PARTIAL", "reason": "Deterministic checks exist; Docker/cleanup/main integration remain release gates."},
    ]
