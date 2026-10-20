"""Secret-free local readiness checks for final hardening."""

from __future__ import annotations

from .storage import CURRENT_SCHEMA_VERSION


def local_readiness(db) -> dict:
    try:
        integrity, schema_version = db.readiness_snapshot()
        return {
            "database_integrity": integrity == "ok",
            "database_integrity_result": integrity,
            "schema_version": schema_version,
            "secret_free": True,
            "ready_for_local_tests": integrity == "ok" and int(schema_version or 0) == CURRENT_SCHEMA_VERSION,
        }
    except Exception as exc:
        return {
            "database_integrity": False,
            "database_integrity_result": type(exc).__name__,
            "schema_version": None,
            "secret_free": True,
            "ready_for_local_tests": False,
        }
