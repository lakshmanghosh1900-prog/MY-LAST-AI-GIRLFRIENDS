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
                applied.add(3)
            if 4 not in applied:
                self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    path TEXT NOT NULL UNIQUE,
                    content_sha256 TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    suffix TEXT NOT NULL,
                    indexed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS document_chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id),
                    ordinal INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(document_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_document_chunks_search ON document_chunks(document_id, ordinal);
                """)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (4, utc_now()),
                )
                applied.add(4)
            if 5 not in applied:
                self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS research_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL CHECK(status IN ('RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED')),
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS research_sources (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES research_runs(id),
                    ordinal INTEGER NOT NULL,
                    requested_url TEXT NOT NULL,
                    final_url TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    byte_count INTEGER NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    content TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    UNIQUE(run_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS idx_research_sources_run ON research_sources(run_id, ordinal);
                """)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (5, utc_now()),
                )
                applied.add(5)
            if 6 not in applied:
                self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    title TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    run_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('SCHEDULED', 'CANCELLED', 'COMPLETED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schedule_runs (
                    id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL REFERENCES schedules(id),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')),
                    task_id TEXT REFERENCES tasks(id),
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    reason TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(status, run_at);
                """)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (6, utc_now()),
                )
                applied.add(6)
            if 7 not in applied:
                self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    identity_hash TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('ENROLLED', 'REVOKED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_at TEXT
                );
                CREATE TABLE IF NOT EXISTS connectors (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'APPROVED', 'REVOKED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    version TEXT NOT NULL,
                    provenance TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('DRAFT', 'REVIEW', 'APPROVED', 'REVOKED')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    action_type TEXT NOT NULL,
                    parameters_hash TEXT NOT NULL,
                    approver_session_hash TEXT,
                    nonce_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING', 'APPROVED', 'CONSUMED', 'EXPIRED', 'REVOKED')),
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    prompt_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    roles_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (7, utc_now()),
                )
            if 8 not in applied:
                self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS device_pairing_challenges (
                    id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL REFERENCES devices(id),
                    challenge_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pairing_challenges_device
                    ON device_pairing_challenges(device_id, expires_at, consumed_at);
                """)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (8, utc_now()),
                )
            if 9 not in applied:
                self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS action_executions (
                    id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(id),
                    action_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('EXECUTED', 'FAILED')),
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """)
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (9, utc_now()),
                )
                applied.add(9)
            if 10 not in applied:
                columns = {row[1] for row in self.connection.execute("PRAGMA table_info(skills)")}
                if "definition_json" not in columns:
                    self.connection.execute("ALTER TABLE skills ADD COLUMN definition_json TEXT")
                self.connection.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (10, utc_now()),
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

    def upsert_document(
        self,
        path: str,
        content_sha256: str,
        byte_count: int,
        suffix: str,
        chunks: tuple[str, ...],
    ) -> dict:
        now = utc_now()
        with self.transaction():
            existing = self.connection.execute(
                "SELECT id FROM documents WHERE path = ?", (path,)
            ).fetchone()
            document_id = str(existing["id"]) if existing else self.new_id()
            self.connection.execute(
                """INSERT INTO documents(id, path, content_sha256, byte_count, suffix, indexed_at, updated_at, deleted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                   ON CONFLICT(path) DO UPDATE SET content_sha256=excluded.content_sha256,
                     byte_count=excluded.byte_count, suffix=excluded.suffix,
                     indexed_at=excluded.indexed_at, updated_at=excluded.updated_at,
                     deleted_at=NULL""",
                (document_id, path, content_sha256, byte_count, suffix, now, now),
            )
            self.connection.execute("DELETE FROM document_chunks WHERE document_id = ?", (document_id,))
            for ordinal, content in enumerate(chunks):
                self.connection.execute(
                    "INSERT INTO document_chunks(id, document_id, ordinal, content, created_at) VALUES (?, ?, ?, ?, ?)",
                    (self.new_id(), document_id, ordinal, content, now),
                )
        return self.get_document(document_id) or {}

    def get_document(self, document_id: str) -> dict | None:
        row = self.connection.execute(
            """SELECT id, path, content_sha256, byte_count, suffix, indexed_at, updated_at
               FROM documents WHERE id = ? AND deleted_at IS NULL""",
            (document_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["chunks"] = [
            dict(item) for item in self.connection.execute(
                "SELECT ordinal, content FROM document_chunks WHERE document_id = ? ORDER BY ordinal",
                (document_id,),
            ).fetchall()
        ]
        return result

    def list_documents(self, limit: int = 100) -> list[dict]:
        rows = self.connection.execute(
            """SELECT id, path, content_sha256, byte_count, suffix, indexed_at, updated_at,
                      (SELECT COUNT(*) FROM document_chunks c WHERE c.document_id = d.id) AS chunk_count
               FROM documents d WHERE deleted_at IS NULL ORDER BY updated_at DESC, id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def search_documents(self, query: str, limit: int = 20) -> list[dict]:
        rows = self.connection.execute(
            """SELECT d.id, d.path, d.content_sha256, c.ordinal, c.content
               FROM documents d JOIN document_chunks c ON c.document_id = d.id
               WHERE d.deleted_at IS NULL AND instr(lower(c.content), lower(?)) > 0
               ORDER BY d.updated_at DESC, d.id DESC, c.ordinal ASC LIMIT ?""",
            (query, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def list_document_chunks_for_answer(self, limit: int = 200) -> list[dict]:
        rows = self.connection.execute(
            """SELECT d.id AS document_id, d.path, d.content_sha256, c.ordinal, c.content
               FROM documents d JOIN document_chunks c ON c.document_id = d.id
               WHERE d.deleted_at IS NULL
               ORDER BY d.updated_at DESC, d.id DESC, c.ordinal ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_document(self, document_id: str) -> bool:
        with self.transaction():
            cursor = self.connection.execute(
                "UPDATE documents SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
                (utc_now(), utc_now(), document_id),
            )
        return cursor.rowcount == 1

    def create_research_run(self) -> str:
        run_id = self.new_id()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO research_runs(id, status, created_at) VALUES (?, 'RUNNING', ?)",
                (run_id, utc_now()),
            )
        return run_id

    def add_research_source(self, run_id: str, ordinal: int, source: dict, content: str) -> None:
        with self.transaction():
            self.connection.execute(
                """INSERT INTO research_sources(
                    id, run_id, ordinal, requested_url, final_url, content_type,
                    byte_count, content_sha256, content, excerpt, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (self.new_id(), run_id, ordinal, source["requested_url"], source["final_url"],
                 source["content_type"], source["byte_count"], source["content_sha256"],
                 content, source["excerpt"], utc_now()),
            )

    def finish_research_run(self, run_id: str, status: str) -> None:
        with self.transaction():
            self.connection.execute(
                "UPDATE research_runs SET status = ?, completed_at = ? WHERE id = ?",
                (status, utc_now(), run_id),
            )

    def get_research_run(self, run_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT id, status, created_at, completed_at FROM research_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["sources"] = [
            dict(item) for item in self.connection.execute(
                """SELECT id, ordinal, requested_url, final_url, content_type, byte_count,
                          content_sha256, excerpt, fetched_at
                   FROM research_sources WHERE run_id = ? ORDER BY ordinal""",
                (run_id,),
            ).fetchall()
        ]
        return result

    def get_research_sources_with_content(self, run_id: str) -> list[dict]:
        rows = self.connection.execute(
            """SELECT id, ordinal, requested_url, final_url, content_type, byte_count,
                      content_sha256, content, excerpt, fetched_at
               FROM research_sources WHERE run_id = ? ORDER BY ordinal""",
            (run_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_schedule(self, conversation_id: str, title: str, prompt: str, run_at: str) -> dict:
        schedule_id = self.new_id()
        now = utc_now()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO schedules(id, conversation_id, title, prompt, run_at, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'SCHEDULED', ?, ?)",
                (schedule_id, conversation_id, title, prompt, run_at, now, now),
            )
        return self.get_schedule(schedule_id) or {}

    def get_schedule(self, schedule_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
        return dict(row) if row else None

    def list_schedules(self, conversation_id: str | None = None) -> list[dict]:
        if conversation_id:
            rows = self.connection.execute("SELECT * FROM schedules WHERE conversation_id = ? ORDER BY run_at, id", (conversation_id,)).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM schedules ORDER BY run_at, id").fetchall()
        return [dict(row) for row in rows]

    def cancel_schedule(self, schedule_id: str) -> bool:
        with self.transaction():
            cursor = self.connection.execute(
                "UPDATE schedules SET status = 'CANCELLED', updated_at = ? WHERE id = ? AND status = 'SCHEDULED'",
                (utc_now(), schedule_id),
            )
        return cursor.rowcount == 1

    def due_schedules(self, now: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT * FROM schedules WHERE status = 'SCHEDULED' AND run_at <= ? ORDER BY run_at, id",
            (now,),
        ).fetchall()
        return [dict(row) for row in rows]

    def create_schedule_run(self, schedule_id: str) -> dict:
        run_id = self.new_id()
        key = f"schedule:{schedule_id}"
        now = utc_now()
        with self.transaction():
            existing = self.connection.execute("SELECT * FROM schedule_runs WHERE idempotency_key = ?", (key,)).fetchone()
            if existing:
                return dict(existing)
            self.connection.execute(
                "INSERT INTO schedule_runs(id, schedule_id, idempotency_key, status, created_at) VALUES (?, ?, ?, 'PENDING', ?)",
                (run_id, schedule_id, key, now),
            )
        return self.get_schedule_run(run_id) or {}

    def claim_schedule_run(self, run_id: str) -> dict | None:
        """Atomically claim a pending schedule run for execution.

        The conditional update is performed in the same immediate transaction
        that reads the claimed row.  A caller that loses the race receives
        ``None`` and must not execute the schedule.
        """

        with self.transaction():
            cursor = self.connection.execute(
                "UPDATE schedule_runs SET status = 'RUNNING' WHERE id = ? AND status = 'PENDING'",
                (run_id,),
            )
            if cursor.rowcount != 1:
                return None
            row = self.connection.execute("SELECT * FROM schedule_runs WHERE id = ?", (run_id,)).fetchone()
            return dict(row) if row else None

    def get_schedule_run(self, run_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM schedule_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def update_schedule_run(self, run_id: str, status: str, task_id: str | None = None, reason: str | None = None) -> None:
        with self.transaction():
            self.connection.execute(
                "UPDATE schedule_runs SET status = ?, task_id = COALESCE(?, task_id), completed_at = CASE WHEN ? IN ('SUCCEEDED', 'FAILED', 'CANCELLED') THEN ? ELSE completed_at END, reason = ? WHERE id = ?",
                (status, task_id, status, utc_now(), reason, run_id),
            )

    def complete_schedule(self, schedule_id: str) -> None:
        with self.transaction():
            self.connection.execute("UPDATE schedules SET status = 'COMPLETED', updated_at = ? WHERE id = ?", (utc_now(), schedule_id))

    def enroll_device(self, name: str, identity_hash: str) -> dict:
        device_id = self.new_id()
        now = utc_now()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO devices(id, name, identity_hash, status, created_at, updated_at) VALUES (?, ?, ?, 'ENROLLED', ?, ?)",
                (device_id, name, identity_hash, now, now),
            )
        return self.get_device(device_id) or {}

    def get_device(self, device_id: str) -> dict | None:
        row = self.connection.execute("SELECT id, name, status, created_at, updated_at, last_seen_at FROM devices WHERE id = ?", (device_id,)).fetchone()
        return dict(row) if row else None

    def list_devices(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT id, name, status, created_at, updated_at, last_seen_at FROM devices ORDER BY created_at, id").fetchall()]

    def revoke_device(self, device_id: str) -> bool:
        with self.transaction():
            cursor = self.connection.execute("UPDATE devices SET status = 'REVOKED', updated_at = ? WHERE id = ? AND status = 'ENROLLED'", (utc_now(), device_id))
        return cursor.rowcount == 1

    def verify_device_identity(self, device_id: str, identity_hash: str) -> bool:
        row = self.connection.execute("SELECT status, identity_hash FROM devices WHERE id = ?", (device_id,)).fetchone()
        if not row or row["status"] != "ENROLLED":
            return False
        if row["identity_hash"] != identity_hash:
            return False
        with self.transaction():
            self.connection.execute("UPDATE devices SET last_seen_at = ?, updated_at = ? WHERE id = ?", (utc_now(), utc_now(), device_id))
        return True

    def create_pairing_challenge(self, device_id: str, challenge_hash: str, expires_at: str) -> dict:
        challenge_id = self.new_id()
        now = utc_now()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO device_pairing_challenges(id, device_id, challenge_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (challenge_id, device_id, challenge_hash, expires_at, now),
            )
        row = self.connection.execute(
            "SELECT id, device_id, expires_at, created_at, consumed_at FROM device_pairing_challenges WHERE id = ?",
            (challenge_id,),
        ).fetchone()
        return dict(row) if row else {}

    def verify_and_consume_pairing_challenge(
        self, device_id: str, challenge_id: str, challenge_hash: str, identity_hash: str
    ) -> bool:
        now = utc_now()
        with self.transaction():
            row = self.connection.execute(
                """
                SELECT d.status, d.identity_hash, c.challenge_hash, c.expires_at, c.consumed_at
                FROM devices AS d
                JOIN device_pairing_challenges AS c ON c.device_id = d.id
                WHERE d.id = ? AND c.id = ?
                """,
                (device_id, challenge_id),
            ).fetchone()
            if (
                not row
                or row["status"] != "ENROLLED"
                or row["identity_hash"] != identity_hash
                or row["challenge_hash"] != challenge_hash
                or row["consumed_at"] is not None
                or row["expires_at"] <= now
            ):
                return False
            self.connection.execute(
                "UPDATE device_pairing_challenges SET consumed_at = ? WHERE id = ? AND consumed_at IS NULL",
                (now, challenge_id),
            )
            self.connection.execute(
                "UPDATE devices SET last_seen_at = ?, updated_at = ? WHERE id = ?",
                (now, now, device_id),
            )
        return True

    def add_connector(self, name: str, endpoint: str, scope: str) -> dict:
        connector_id = self.new_id()
        now = utc_now()
        with self.transaction():
            self.connection.execute("INSERT INTO connectors(id, name, endpoint, scope, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'DRAFT', ?, ?)", (connector_id, name, endpoint, scope, now, now))
        return self.get_connector(connector_id) or {}

    def get_connector(self, connector_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM connectors WHERE id = ?", (connector_id,)).fetchone()
        return dict(row) if row else None

    def list_connectors(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM connectors ORDER BY created_at, id").fetchall()]

    def transition_connector(self, connector_id: str, status: str) -> bool:
        with self.transaction():
            cursor = self.connection.execute("UPDATE connectors SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), connector_id))
        return cursor.rowcount == 1

    def add_skill(
        self,
        name: str,
        version: str,
        provenance: str,
        capabilities_json: str,
        definition_json: str | None = None,
    ) -> dict:
        skill_id = self.new_id(); now = utc_now()
        with self.transaction():
            self.connection.execute(
                "INSERT INTO skills(id, name, version, provenance, capabilities_json, definition_json, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?)",
                (skill_id, name, version, provenance, capabilities_json, definition_json, now, now),
            )
        return self.get_skill(skill_id) or {}

    def get_skill(self, skill_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        return dict(row) if row else None

    def list_skills(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM skills ORDER BY created_at, id").fetchall()]

    def transition_skill(self, skill_id: str, status: str) -> bool:
        with self.transaction():
            cursor = self.connection.execute("UPDATE skills SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), skill_id))
        return cursor.rowcount == 1

    def create_approval(self, action_type: str, parameters_hash: str, nonce_hash: str, expires_at: str) -> dict:
        approval_id = self.new_id(); now = utc_now()
        with self.transaction():
            self.connection.execute("INSERT INTO approvals(id, action_type, parameters_hash, nonce_hash, status, expires_at, created_at, updated_at) VALUES (?, ?, ?, ?, 'PENDING', ?, ?, ?)", (approval_id, action_type, parameters_hash, nonce_hash, expires_at, now, now))
        return self.get_approval(approval_id) or {}

    def get_approval(self, approval_id: str) -> dict | None:
        row = self.connection.execute("SELECT id, action_type, parameters_hash, status, expires_at, created_at, updated_at FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return dict(row) if row else None

    def get_approval_with_secrets(self, approval_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return dict(row) if row else None

    def execute_local_schedule_approval(self, approval_id: str, conversation_id: str, title: str, prompt: str, run_at: str) -> dict:
        now = utc_now()
        schedule_id = self.new_id()
        execution_id = self.new_id()
        with self.transaction():
            approval = self.connection.execute("SELECT status, expires_at, action_type FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            if not approval or approval["status"] != "APPROVED" or approval["action_type"] != "local.schedule.create" or approval["expires_at"] <= now:
                raise ValueError("approval is not executable")
            self.connection.execute(
                "INSERT INTO schedules(id, conversation_id, title, prompt, run_at, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'SCHEDULED', ?, ?)",
                (schedule_id, conversation_id, title, prompt, run_at, now, now),
            )
            updated = self.connection.execute(
                "UPDATE approvals SET status = 'CONSUMED', updated_at = ? WHERE id = ? AND status = 'APPROVED'",
                (now, approval_id),
            )
            if updated.rowcount != 1:
                raise ValueError("approval was already consumed")
            self.connection.execute(
                "INSERT INTO action_executions(id, approval_id, action_type, status, result_json, created_at) VALUES (?, ?, ?, 'EXECUTED', ?, ?)",
                (execution_id, approval_id, "local.schedule.create", json.dumps({"schedule_id": schedule_id}, sort_keys=True), now),
            )
        return self.get_schedule(schedule_id) or {}

    def list_approvals(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT id, action_type, parameters_hash, status, expires_at, created_at, updated_at FROM approvals ORDER BY created_at, id").fetchall()]

    def transition_approval(self, approval_id: str, status: str, approver_session_hash: str | None = None) -> bool:
        with self.transaction():
            cursor = self.connection.execute("UPDATE approvals SET status = ?, approver_session_hash = COALESCE(?, approver_session_hash), updated_at = ? WHERE id = ?", (status, approver_session_hash, utc_now(), approval_id))
        return cursor.rowcount == 1

    def create_agent_run(self, run_id: str, prompt_hash: str, status: str, depth: int, roles_json: str, evidence_json: str) -> dict:
        now = utc_now()
        with self.transaction():
            self.connection.execute("INSERT INTO agent_runs(id, prompt_hash, status, depth, roles_json, evidence_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (run_id, prompt_hash, status, depth, roles_json, evidence_json, now, now))
        row = self.connection.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else {}

    def list_agent_runs(self) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM agent_runs ORDER BY created_at, id").fetchall()]

    def month_usage(self, bucket_month: str) -> int:
        row = self.connection.execute(
            "SELECT COALESCE(SUM(amount_usd_micros), 0) AS total FROM budget_events WHERE bucket_month = ?",
            (bucket_month,),
        ).fetchone()
        return int(row["total"])
