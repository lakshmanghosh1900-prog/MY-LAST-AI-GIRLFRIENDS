from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from my_last_ai_girlfriends.release import local_readiness
from my_last_ai_girlfriends.storage import Database


class ReleaseReadinessTests(unittest.TestCase):
    def test_readiness_uses_the_database_serialization_boundary(self):
        class NoDirectConnectionAccess:
            @property
            def connection(self):
                raise AssertionError("readiness must not bypass the Database API")

            def readiness_snapshot(self):
                return "ok", 11

        self.assertTrue(local_readiness(NoDirectConnectionAccess())["ready_for_local_tests"])

    def test_readiness_requires_the_exact_current_schema_version(self):
        class SnapshotOnly:
            def __init__(self, schema_version):
                self.schema_version = schema_version

            def readiness_snapshot(self):
                return "ok", self.schema_version

        for schema_version, expected in ((10, False), (11, True)):
            with self.subTest(schema_version=schema_version):
                self.assertEqual(
                    local_readiness(SnapshotOnly(schema_version))["ready_for_local_tests"],
                    expected,
                )

    def test_database_readiness_snapshot_reports_integrity_and_schema(self):
        with tempfile.TemporaryDirectory() as raw:
            db = Database(Path(raw) / "readiness.sqlite3")
            try:
                db.initialize()
                self.assertEqual(db.readiness_snapshot(), ("ok", 11))
                self.assertTrue(local_readiness(db)["ready_for_local_tests"])
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
