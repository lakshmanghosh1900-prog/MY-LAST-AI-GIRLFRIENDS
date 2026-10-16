"""Small SQLite persistence layer with explicit transactions and migrations."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cancel_requested INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS policy_decisions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    decision TEXT NOT NULL,
    code TEXT NOT NULL,
    reason TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_calls (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    estimated_usd_micros INTEGER NOT NULL DEFAULT 0,
    actual_usd_micros INTEGER,
    provider_request_id TEXT,
    error_code TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_events (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    reservation_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    amount_usd_micros INTEGER NOT NULL,
    bucket_month TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    event TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_budget_bucket ON budget_events(bucket_month);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")

    def initialize(self) -> None:
        with self.transaction():
            self.connection.executescript(SCHEMA_SQL)
            self.connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, utc_now()),
            )

    @contextmanager
    def transaction(self, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield self.connection
            except Exception:
                self.connection.rollback()
                raise
            else:
                self.connection.commit()

    def close(self) -> None:
        with self._lock:
            self.connection.close()

    def new_id(self) -> str:
        return str(uuid.uuid4())

    def create_conversation(self) -> str:
        conversation_id = self.new_id()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO conversations(id, created_at) VALUES (?, ?)",
                (conversation_id, utc_now()),
            )
        return conversation_id

    def conversation_exists(self, conversation_id: str) -> bool:
        row = self.connection.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return row is not None

    def add_message(self, conversation_id: str, role: str, content: str) -> str:
        message_id = self.new_id()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO messages(id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content, utc_now()),
            )
        return message_id

    def get_messages(self, conversation_id: str) -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at, id",
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_task(self, conversation_id: str) -> str:
        task_id = self.new_id()
        now = utc_now()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO tasks(id, conversation_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (task_id, conversation_id, "CREATED", now, now),
            )
        return task_id

    def update_task(self, task_id: str, status: str, reason: str | None = None) -> None:
        with self.transaction():
            self.connection.execute(
                "UPDATE tasks SET status = ?, reason = ?, updated_at = ? WHERE id = ?",
                (status, reason, utc_now(), task_id),
            )

    def get_task(self, task_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def add_policy_decision(self, task_id: str, decision: str, code: str, reason: str, policy_version: str) -> None:
        with self.transaction():
            self.connection.execute(
                "INSERT INTO policy_decisions(id, task_id, decision, code, reason, policy_version, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (self.new_id(), task_id, decision, code, reason, policy_version, utc_now()),
            )

    def add_provider_call(self, task_id: str, provider: str, model: str, status: str, input_tokens: int = 0, output_tokens: int = 0,
                          estimated_usd_micros: int = 0, actual_usd_micros: int | None = None,
                          provider_request_id: str | None = None, error_code: str | None = None) -> None:
        with self.transaction():
            self.connection.execute(
                """INSERT INTO provider_calls(
                    id, task_id, provider, model, status, input_tokens, output_tokens,
                    estimated_usd_micros, actual_usd_micros, provider_request_id,
                    error_code, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.new_id(), task_id, provider, model, status, input_tokens, output_tokens,
                 estimated_usd_micros, actual_usd_micros, provider_request_id, error_code, utc_now()),
            )

    def add_audit(self, event: str, metadata: dict, task_id: str | None = None) -> None:
        with self.transaction():
            self.connection.execute(
                "INSERT INTO audit_events(id, task_id, event, metadata_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (self.new_id(), task_id, event, json.dumps(metadata, sort_keys=True, separators=(",", ":")), utc_now()),
            )

    def month_usage(self, bucket_month: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(amount_usd_micros), 0) AS total FROM budget_events WHERE bucket_month = ?",
            (bucket_month,),
        ).fetchone()
        return int(row["total"])
