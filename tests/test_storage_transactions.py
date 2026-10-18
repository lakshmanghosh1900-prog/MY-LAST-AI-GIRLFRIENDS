from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from my_last_ai_girlfriends.storage import Database


class CommitFailureConnection(sqlite3.Connection):
    fail_next_commit = False
    rollback_count = 0

    def commit(self) -> None:
        if self.fail_next_commit:
            self.fail_next_commit = False
            raise sqlite3.OperationalError("injected commit failure")
        super().commit()

    def rollback(self) -> None:
        self.rollback_count += 1
        super().rollback()


class CommitFailureDatabase(Database):
    def _connect(self, vfs: str | None = None) -> sqlite3.Connection:
        return sqlite3.connect(
            self.path,
            factory=CommitFailureConnection,
            check_same_thread=False,
            isolation_level=None,
        )


class StorageTransactionTests(unittest.TestCase):
    def test_commit_failure_rolls_back_and_allows_later_operation(self):
        with tempfile.TemporaryDirectory() as raw:
            db = CommitFailureDatabase(Path(raw) / "transaction.sqlite3")
            db.initialize()
            db.connection.fail_next_commit = True

            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, "injected commit failure"):
                    db.create_conversation()

                self.assertEqual(db.connection.rollback_count, 1)
                self.assertEqual(
                    db.connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                    0,
                )

                conversation_id = db.create_conversation()
                self.assertTrue(db.conversation_exists(conversation_id))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
