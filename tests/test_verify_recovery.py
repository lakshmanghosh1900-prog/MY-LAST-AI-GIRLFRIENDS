from __future__ import annotations

import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify-recovery.py"
SPEC = importlib.util.spec_from_file_location("verify_recovery", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
VERIFY_RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY_RECOVERY)


class VerifyRecoveryTests(unittest.TestCase):
    def test_read_only_backup_includes_committed_wal_rows_without_changing_candidate(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            candidate = root / "candidate.sqlite3"
            isolated = root / "isolated.sqlite3"
            candidate_wal = Path(f"{candidate}-wal")
            candidate_shm = Path(f"{candidate}-shm")

            connection = sqlite3.connect(candidate)
            try:
                self.assertEqual(connection.execute("PRAGMA journal_mode=WAL").fetchone()[0], "wal")
                connection.execute("PRAGMA wal_autocheckpoint=1000000")
                connection.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
                connection.executemany(
                    "INSERT INTO records (value) VALUES (?)",
                    [("first committed row",), ("second committed row",), ("third committed row",)],
                )
                connection.commit()
                self.assertGreater(candidate_wal.stat().st_size, 0)
                self.assertTrue(candidate_shm.exists())
                before = {
                    candidate: candidate.read_bytes(),
                    candidate_wal: candidate_wal.read_bytes(),
                    candidate_shm: candidate_shm.read_bytes(),
                }

                VERIFY_RECOVERY.create_isolated_database(candidate, isolated)

                with sqlite3.connect(isolated) as isolated_connection:
                    rows = isolated_connection.execute("SELECT id, value FROM records ORDER BY id").fetchall()
                self.assertEqual(
                    rows,
                    [(1, "first committed row"), (2, "second committed row"), (3, "third committed row")],
                )
                self.assertEqual(
                    {path: path.read_bytes() for path in before},
                    before,
                )
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
