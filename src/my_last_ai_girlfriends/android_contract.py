"""Shared, dependency-free API contract for the future Android companion."""

from __future__ import annotations

from dataclasses import dataclass


ANDROID_API_CONTRACT_VERSION = "android-companion-contract-0.1.0"
PAIRING_CHALLENGE_ROUTE = "/v1/devices/{device_id}/pairing-challenge"
PAIRING_VERIFY_ROUTE = "/v1/devices/{device_id}/verify-pairing"
DIAGNOSTICS_ROUTE = "/v1/devices/{device_id}/diagnostics"


@dataclass(frozen=True)
class ConnectionDiagnostics:
    device_id: str
    device_status: str
    transport: str
    encrypted: bool
    replay_protected: bool
    pairing_available: bool
    last_seen_at: str | None

    def as_dict(self) -> dict:
        return {
            "contract_version": ANDROID_API_CONTRACT_VERSION,
            "device_id": self.device_id,
            "device_status": self.device_status,
            "transport": self.transport,
            "encrypted": self.encrypted,
            "replay_protected": self.replay_protected,
            "pairing_available": self.pairing_available,
            "last_seen_at": self.last_seen_at,
        }
