"""Validate a SQLite recovery candidate in an isolated temporary application.

Usage:
    uv run --locked python scripts/verify-recovery.py data/migration-backups/<candidate>.sqlite3

The candidate is copied into a temporary directory. It is never modified in
place, and the script never prints authentication tokens or conversation text.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import shutil
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from my_last_ai_girlfriends.config import Config, generate_auth_token, load_environment  # noqa: E402
from my_last_ai_girlfriends.http_api import MyLastAIGirlfriendsHTTPServer  # noqa: E402
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService  # noqa: E402


def create_isolated_database(candidate: Path, isolated_path: Path) -> None:
    """Back up a candidate through a read-only connection, including its WAL."""
    with tempfile.TemporaryDirectory(prefix="mlag-recovery-source-") as raw:
        staged_candidate = Path(raw) / candidate.name
        shutil.copyfile(candidate, staged_candidate)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{candidate}{suffix}")
            if sidecar.exists():
                shutil.copyfile(sidecar, Path(f"{staged_candidate}{suffix}"))

        source = sqlite3.connect(f"{staged_candidate.resolve().as_uri()}?mode=ro", uri=True)
        try:
            destination = sqlite3.connect(isolated_path)
            try:
                source.backup(destination)
                destination.commit()
            finally:
                destination.close()
        finally:
            source.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    if not candidate.is_file():
        parser.error(f"recovery candidate does not exist: {candidate}")
    candidate_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()

    with tempfile.TemporaryDirectory(prefix="mlag-recovery-") as raw:
        root = Path(raw)
        data_dir = root / "data"
        workspace = root / "workspace"
        data_dir.mkdir()
        workspace.mkdir()
        isolated_path = data_dir / "my_last_ai_girlfriends.sqlite3"
        create_isolated_database(candidate, isolated_path)
        token = generate_auth_token()
        env = {
            "MLAG_AUTH_TOKEN": token,
            "MLAG_HOST": "127.0.0.1",
            "MLAG_PORT": "8787",
            "MLAG_TRUSTED_HOSTS": "127.0.0.1,localhost",
            "MLAG_MODE": "offline",
            "MLAG_PROVIDER": "gemini",
            "MLAG_MODEL": "gemini-3.8-flash",
            "MLAG_PROVIDER_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "MLAG_ALLOW_REMOTE_PERSONAL_DATA": "false",
            "MLAG_DATA_DIR": str(data_dir),
            "MLAG_ALLOWED_ROOT": str(workspace),
        }
        config = Config.from_report(load_environment(root / "missing.env", env))
        service = MyLastAIGirlfriendsService(config)
        server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            connection.request("GET", "/v1/health", headers=headers)
            health_response = connection.getresponse()
            health = json.loads(health_response.read())
            connection.request("GET", "/v1/conversations", headers=headers)
            conversations_response = connection.getresponse()
            conversations = json.loads(conversations_response.read())
            connection.request("POST", "/v1/conversations", body="{}", headers=headers)
            create_response = connection.getresponse()
            created = json.loads(create_response.read())
            connection.request("POST", f"/v1/conversations/{created['id']}/messages", body=json.dumps({"content": "recovery smoke"}), headers=headers)
            message_response = connection.getresponse()
            message = json.loads(message_response.read())
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            service.close()

        read_only = sqlite3.connect(f"file:{isolated_path}?mode=ro", uri=True)
        try:
            integrity = read_only.execute("PRAGMA integrity_check").fetchone()[0]
            schema = read_only.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
            counts = {
                name: read_only.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                for name in ("conversations", "messages", "tasks", "provider_calls", "budget_events", "audit_events")
            }
            memory_count = read_only.execute("SELECT COUNT(*) FROM memory_items").fetchone()[0]
            schedule_count = read_only.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]
        finally:
            read_only.close()

    print(f"candidate_sha256={candidate_sha}")
    print(f"integrity={integrity}")
    print(f"schema_version={schema}")
    print(f"counts_after_isolated_smoke={counts}")
    print(f"memory_count={memory_count} schedule_count={schedule_count}")
    print(f"health_status={health_response.status} state={health['state']} database={health['database']}")
    print(f"conversation_list_status={conversations_response.status} count={len(conversations['conversations'])}")
    print(f"authenticated_create_status={create_response.status}")
    print(f"authenticated_message_status={message_response.status} task_status={message['status']} ai_generated={message['ai_generated']}")
    return 0 if integrity == "ok" and health_response.status == 200 and message_response.status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
