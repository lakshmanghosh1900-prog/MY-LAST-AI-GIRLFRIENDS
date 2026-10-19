from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.storage import Database


class StorageHeaderTests(unittest.TestCase):
    def test_invalid_database_header_is_rejected_before_connect_without_mutation(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "invalid.sqlite3"
            original = b"owner-preserved invalid database bytes"
            path.write_bytes(original)

            with patch.object(Database, "_connect", side_effect=AssertionError("connection must not open")):
                with self.assertRaisesRegex(sqlite3.DatabaseError, "invalid header"):
                    Database(path)

            self.assertEqual(path.read_bytes(), original)
            self.assertFalse(Path(str(path) + "-wal").exists())
            self.assertFalse(Path(str(path) + "-shm").exists())

    def test_valid_existing_sqlite_database_header_is_accepted(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "valid.sqlite3"
            connection = sqlite3.connect(path)
            try:
                connection.execute("CREATE TABLE marker(value TEXT NOT NULL)")
                connection.execute("INSERT INTO marker(value) VALUES ('preserve')")
                connection.commit()
            finally:
                connection.close()

            db = Database(path)
            try:
                self.assertEqual(db.connection.execute("SELECT value FROM marker").fetchone()[0], "preserve")
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
