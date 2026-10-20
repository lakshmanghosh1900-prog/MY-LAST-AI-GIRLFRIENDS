from __future__ import annotations

import multiprocessing
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.storage import Database, StorageError, migrate_legacy_database


def _create_minimal_legacy_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
        connection.execute("INSERT INTO marker(value) VALUES ('legacy')")
        connection.commit()
    finally:
        connection.close()


def _concurrent_migration_worker(data_dir: str, ready, start, results) -> None:
    ready.put(os.getpid())
    if not start.wait(30):
        results.put(("error", "start barrier timeout"))
        return
    try:
        result = migrate_legacy_database(Path(data_dir))
        results.put(("ok", result.name if result else None))
    except Exception as exc:  # pragma: no cover - assertion data is sent to parent
        results.put(("error", type(exc).__name__, str(exc)))


class MigrationTests(unittest.TestCase):
    def test_legacy_database_is_backed_up_and_copied_without_row_loss(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw)
            legacy = data / "jarvis.sqlite3"
            connection = sqlite3.connect(legacy)
            connection.executescript("""
                CREATE TABLE conversations(id TEXT PRIMARY KEY, created_at TEXT NOT NULL);
                CREATE TABLE messages(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE tasks(id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, status TEXT NOT NULL, reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, cancel_requested INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE policy_decisions(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, decision TEXT NOT NULL, code TEXT NOT NULL, reason TEXT NOT NULL, policy_version TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE provider_calls(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, provider TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, estimated_usd_micros INTEGER NOT NULL DEFAULT 0, actual_usd_micros INTEGER, provider_request_id TEXT, error_code TEXT, created_at TEXT NOT NULL);
                CREATE TABLE budget_events(id TEXT PRIMARY KEY, task_id TEXT NOT NULL, reservation_id TEXT NOT NULL, event_type TEXT NOT NULL, amount_usd_micros INTEGER NOT NULL, bucket_month TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
                CREATE TABLE audit_events(id TEXT PRIMARY KEY, task_id TEXT, event TEXT NOT NULL, metadata_json TEXT NOT NULL, created_at TEXT NOT NULL);
                INSERT INTO conversations VALUES ('c1','now');
                INSERT INTO messages VALUES ('m1','c1','user','hello','now');
                INSERT INTO tasks VALUES ('t1','c1','SUCCEEDED',NULL,'now','now',0);
            """)
            connection.close()
            canonical = migrate_legacy_database(data)
            self.assertIsNotNone(canonical)
            self.assertFalse((data / "jarvis.sqlite3").exists())
            self.assertTrue((data / "my_last_ai_girlfriends.sqlite3").exists())
            self.assertTrue(list((data / "migration-backups").glob("legacy-preserved.*.sqlite3")))
            self.assertIsNone(migrate_legacy_database(data))
            migrated = Database(data / "my_last_ai_girlfriends.sqlite3")
            migrated.initialize()
            self.assertEqual(migrated.connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], 1)
            self.assertEqual(migrated.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
            self.assertEqual(migrated.connection.execute("SELECT conversation_id FROM tasks WHERE id = 't1'").fetchone()[0], "c1")
            self.assertEqual(migrated.connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(migrated.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 11)
            self.assertIn("definition_json", {row[1] for row in migrated.connection.execute("PRAGMA table_info(skills)")})
            migrated.close()

    def test_failed_migration_rolls_back_ddl_and_state(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "migration.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            connection.executemany(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                [(1, "before"), (2, "before")],
            )
            connection.commit()
            connection.close()

            database = Database(path)
            state_inserts = 0

            def deny_migration_state_insert(action, table, _column, _database, _source):
                nonlocal state_inserts
                if action == sqlite3.SQLITE_INSERT and table == "schema_migrations":
                    state_inserts += 1
                    if state_inserts == 3:
                        return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            database.connection.set_authorizer(deny_migration_state_insert)
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    database.initialize()
                self.assertEqual(state_inserts, 3)
                self.assertIsNone(
                    database.connection.execute(
                        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memory_items'"
                    ).fetchone(),
                    "migration 3 DDL must roll back",
                )
                self.assertEqual(
                    database.connection.execute(
                        "SELECT MAX(version) FROM schema_migrations"
                    ).fetchone()[0],
                    2,
                )
            finally:
                database.close()

    def test_legacy_and_canonical_conflict_stops(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw)
            sqlite3.connect(data / "jarvis.sqlite3").close()
            sqlite3.connect(data / "my_last_ai_girlfriends.sqlite3").close()
            with self.assertRaises(StorageError):
                migrate_legacy_database(data)

    def test_canonical_appearing_during_install_is_not_clobbered(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw)
            legacy = data / "jarvis.sqlite3"
            canonical = data / "my_last_ai_girlfriends.sqlite3"
            _create_minimal_legacy_database(legacy)
            real_link = os.link

            def create_canonical_before_link(source, destination):
                self.assertEqual(Path(destination), canonical)
                canonical.write_bytes(b"canonical-created-during-install")
                return real_link(source, destination)

            with patch(
                "my_last_ai_girlfriends.storage.os.link",
                side_effect=create_canonical_before_link,
            ), self.assertRaisesRegex(StorageError, "appeared"):
                migrate_legacy_database(data)

            self.assertEqual(canonical.read_bytes(), b"canonical-created-during-install")
            self.assertTrue(legacy.exists())
            self.assertEqual(
                len(list(data.glob("my_last_ai_girlfriends-migration.*.tmp"))),
                1,
            )

    def test_unsupported_hard_link_preserves_source_and_temporary(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw)
            legacy = data / "jarvis.sqlite3"
            canonical = data / "my_last_ai_girlfriends.sqlite3"
            _create_minimal_legacy_database(legacy)

            with patch(
                "my_last_ai_girlfriends.storage.os.link",
                side_effect=OSError("hard links unavailable"),
            ), self.assertRaisesRegex(StorageError, "hard-link"):
                migrate_legacy_database(data)

            self.assertTrue(legacy.exists())
            self.assertFalse(canonical.exists())
            self.assertEqual(
                len(list(data.glob("my_last_ai_girlfriends-migration.*.tmp"))),
                1,
            )
            self.assertEqual(
                len(list((data / "migration-backups").glob("legacy-source.*.sqlite3"))),
                1,
            )

    def test_concurrent_spawned_migrations_are_serialized(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw)
            _create_minimal_legacy_database(data / "jarvis.sqlite3")
            context = multiprocessing.get_context("spawn")
            ready = context.Queue()
            start = context.Event()
            results = context.Queue()
            processes = [
                context.Process(
                    target=_concurrent_migration_worker,
                    args=(str(data), ready, start, results),
                )
                for _ in range(2)
            ]
            try:
                for process in processes:
                    process.start()
                for _ in processes:
                    ready.get(timeout=30)
                start.set()
                outcomes = [results.get(timeout=30) for _ in processes]
            finally:
                start.set()
                for process in processes:
                    process.join(timeout=30)
                for process in processes:
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=30)

            self.assertEqual(
                sorted(outcomes, key=repr),
                sorted([("ok", None), ("ok", "my_last_ai_girlfriends.sqlite3")], key=repr),
            )
            self.assertTrue((data / "my_last_ai_girlfriends.sqlite3").exists())
            self.assertFalse((data / "jarvis.sqlite3").exists())


if __name__ == "__main__":
    unittest.main()
