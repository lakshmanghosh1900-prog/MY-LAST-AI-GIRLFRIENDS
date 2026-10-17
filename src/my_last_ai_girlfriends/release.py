"""Secret-free local readiness checks for final hardening."""

from __future__ import annotations


def local_readiness(db) -> dict:
    try:
        integrity = db.connection.execute("PRAGMA integrity_check").fetchone()[0]
        schema_version = db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        return {
            "database_integrity": integrity == "ok",
            "database_integrity_result": integrity,
            "schema_version": schema_version,
            "secret_free": True,
            "ready_for_local_tests": integrity == "ok" and int(schema_version or 0) >= 10,
        }
    except Exception as exc:
        return {
            "database_integrity": False,
            "database_integrity_result": type(exc).__name__,
            "schema_version": None,
            "secret_free": True,
            "ready_for_local_tests": False,
        }
