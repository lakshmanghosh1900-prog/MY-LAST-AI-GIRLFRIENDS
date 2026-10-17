"""SQLite storage, schema migration and safe legacy database preservation."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote


class StorageError(RuntimeError):
    """Raised when storage cannot be migrated or opened safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _unique_path(directory: Path, prefix: str, suffix: str = ".sqlite3") -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{prefix}.{stamp}{suffix}"
    counter = 1
    while path.exists():
        path = directory / f"{prefix}.{stamp}.{counter}{suffix}"
        counter += 1
    return path


def migrate_legacy_database(data_dir: Path) -> Path | None:
    """Migrate a legacy database once and preserve its source in a backup.

    The old filename is recognized only as an explicit recoverability path. The
    source is copied and integrity-checked, then moved into the backup folder
    after the canonical copy is atomically installed. This makes normal
    application restarts idempotent without deleting the recoverable source.
    If both canonical and legacy files exist before a migration, the function
    stops rather than guessing whether they should be merged.
    """

    data_dir.mkdir(parents=True, exist_ok=True)
    legacy = data_dir / "jarvis.sqlite3"
    canonical = data_dir / "my_last_ai_girlfriends.sqlite3"
    if not legacy.exists():
        return None
    if canonical.exists():
        raise StorageError("legacy and canonical databases both exist; resolve the conflict without automatic merging")
    backup_dir = data_dir / "migration-backups"
    backup_dir.mkdir(exist_ok=True)
    backup = _unique_path(backup_dir, "legacy-source")
    source = sqlite3.connect(legacy)
    try:
        source.execute("PRAGMA wal_checkpoint(FULL)")
        integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise StorageError(f"legacy database integrity check failed: {integrity}")
        backup_connection = sqlite3.connect(backup)
        try:
            source.backup(backup_connection)
        finally:
            backup_connection.close()
    finally:
        source.close()
    temporary_canonical = _unique_path(data_dir, "my_last_ai_girlfriends-migration", ".tmp")
    shutil.copy2(backup, temporary_canonical)
    check = sqlite3.connect(temporary_canonical)
    try:
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()
    if integrity != "ok":
        temporary_canonical.unlink(missing_ok=True)
        raise StorageError(f"migrated database integrity check failed: {integrity}")
    os.replace(temporary_canonical, canonical)
    preserved_source = _unique_path(backup_dir, "legacy-preserved")
    try:
        shutil.move(str(legacy), preserved_source)
        for suffix in ("-wal", "-shm"):
            sidecar = Path(f"{legacy}{suffix}")
            if sidecar.exists():
                shutil.move(str(sidecar), Path(f"{preserved_source}{suffix}"))
    except OSError as exc:
        raise StorageError("canonical database installed but legacy source could not be moved into the backup folder") from exc
    return canonical


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_tasks_conversation ON tasks(conversation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_budget_bucket ON budget_events(bucket_month);
"""


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = self._connect()
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            self.connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.OperationalError as exc:
            # Some mounted Windows/virtiofs workspaces can retain a stale WAL
            # sidecar that makes SQLite's default VFS return disk I/O errors.
            # Retry with SQLite's exclusive POSIX VFS only on non-Windows
            # runtimes; native Windows keeps the normal portable VFS path.
            if os.name == "nt" or "disk i/o error" not in str(exc).lower():
                self.connection.close()
                raise
            self.connection.close()
            self.connection = self._connect(vfs="unix-excl")
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA busy_timeout = 5000")

    def _connect(self, vfs: str | None = None) -> sqlite3.Connection:
        if vfs is None:
            return sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        encoded_path = quote(self.path.resolve().as_posix(), safe="/")
        return sqlite3.connect(
            f"file:{encoded_path}?mode=rwc&vfs={vfs}",
            uri=True,
            check_same_thread=False,
            isolation_level=None,
        )

    def initialize(self) -> None:
        with self.transaction():
            self.connection.executescript(SCHEMA_SQL)
            columns = {row[1] for row in self.connection.execute("PRAGMA table_info(conversations)")}
            if "title" not in columns:
                self.connection.execute("ALTER TABLE conversations ADD COLUMN title TEXT")
                self.connection.execute("UPDATE conversations SET title = 'Imported conversation' WHERE title IS NULL")
            if "updated_at" not in columns:
                self.connection.execute("ALTER TABLE conversations ADD COLUMN updated_at TEXT")
                self.connection.execute("UPDATE conversations SET updated_at = created_at WHERE updated_at IS NULL")
            self.connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (1, utc_now()),
            )
            self.connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (2, utc_now()),
            )
            applied = {row[0] for row in self.connection.execute("SELECT version FROM schema_migrations")}
            if 3 not in applied:
                self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL CHECK(scope IN ('global', 'conversation')),
                    conversation_id TEXT REFERENCES conversations(id),
                    content TEXT NOT NULL,
                    data_class TEXT NOT NULL CHECK(data_class IN ('PUBLIC', 'PERSONAL')),
                    source_type TEXT NOT NULL CHECK(source_type IN ('explicit', 'imported')),
                    source_message_id TEXT REFERENCES messages(id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    deleted_at TEXT,
                    confirmed INTEGER NOT NULL DEFAULT 1 CHECK(confirmed IN (0, 1)),
                    CHECK((scope = 'global' AND conversation_id IS NULL) OR
                          (scope = 'conversation' AND conversation_id IS NOT NULL))
                );
                CREATE INDEX IF NOT EXISTS idx_memory_scope ON memory_items(scope, conversation_id, updated_at);
                CREATE INDEX IF NOT EXISTS idx_memory_expiry ON memory_items(expires_at, deleted_at);
                """)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (3, utc_now()),
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
        now = utc_now()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO conversations(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, "New conversation", now, now),
            )
        return conversation_id

    def conversation_exists(self, conversation_id: str) -> bool:
        row = self.connection.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        return row is not None

    def list_conversations(self, limit: int = 50) -> list[dict]:
        rows = self.connection.execute(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def add_message(self, conversation_id: str, role: str, content: str) -> str:
        message_id = self.new_id()
        now = utc_now()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO messages(id, conversation_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
                (message_id, conversation_id, role, content, now),
            )
            if role == "user":
                self.connection.execute(
                    "UPDATE conversations SET title = CASE WHEN title = 'New conversation' THEN ? ELSE title END, updated_at = ? WHERE id = ?",
                    (content[:80] or "New conversation", now, conversation_id),
                )
            else:
                self.connection.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        return message_id

    def get_messages(self, conversation_id: str) -> list[dict[str, str]]:
        rows = self.connection.execute(
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at, id",
            (conversation_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_messages(self, conversation_id: str, limit: int, exclude_id: str | None = None) -> list[dict[str, str]]:
        if exclude_id:
            rows = self.connection.execute(
                "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? AND id != ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (conversation_id, exclude_id, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (conversation_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

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

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.transaction():
            self.connection.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, value, utc_now()),
            )

    def create_memory(
        self,
        scope: str,
        conversation_id: str | None,
        content: str,
        data_class: str,
        expires_at: str | None,
        source_type: str = "explicit",
        source_message_id: str | None = None,
    ) -> dict:
        memory_id = self.new_id()
        now = utc_now()
        with self.transaction():
            self.connection.execute(
                """INSERT INTO memory_items(
                    id, scope, conversation_id, content, data_class, source_type,
                    source_message_id, created_at, updated_at, expires_at, confirmed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
                (memory_id, scope, conversation_id, content, data_class, source_type,
                 source_message_id, now, now, expires_at),
            )
        return self.get_memory(memory_id) or {}

    def get_memory(self, memory_id: str) -> dict | None:
        row = self.connection.execute(
            """SELECT id, scope, conversation_id, content, data_class, source_type,
                      source_message_id, created_at, updated_at, expires_at, confirmed
               FROM memory_items WHERE id = ? AND deleted_at IS NULL""",
            (memory_id,),
        ).fetchone()
        return dict(row) if row else None

    def list_memories(self, conversation_id: str | None = None, limit: int = 100) -> list[dict]:
        now = utc_now()
        if conversation_id is None:
            rows = self.connection.execute(
                """SELECT id, scope, conversation_id, content, data_class, source_type,
                          source_message_id, created_at, updated_at, expires_at, confirmed
                   FROM memory_items
                   WHERE deleted_at IS NULL AND scope = 'global'
                     AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (now, limit),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """SELECT id, scope, conversation_id, content, data_class, source_type,
                          source_message_id, created_at, updated_at, expires_at, confirmed
                   FROM memory_items
                   WHERE deleted_at IS NULL
                     AND (scope = 'global' OR conversation_id = ?)
                     AND (expires_at IS NULL OR expires_at > ?)
                   ORDER BY updated_at DESC, id DESC LIMIT ?""",
                (conversation_id, now, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_memory(self, memory_id: str) -> bool:
        with self.transaction():
            cursor = self.connection.execute(
                "UPDATE memory_items SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (utc_now(), utc_now(), memory_id),
            )
        return cursor.rowcount == 1

    def month_usage(self, bucket_month: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(amount_usd_micros), 0) AS total FROM budget_events WHERE bucket_month = ?",
            (bucket_month,),
        ).fetchone()
        return int(row["total"])
