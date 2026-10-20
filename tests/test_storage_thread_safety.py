from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from my_last_ai_girlfriends.storage import Database


class StorageThreadSafetyTests(unittest.TestCase):
    def test_shared_connection_serializes_mixed_reads_and_transactions(self):
        with tempfile.TemporaryDirectory() as raw:
            db = Database(Path(raw) / "thread-safety.sqlite3")
            db.initialize()
            workers = 8
            iterations = 24
            start = Barrier(workers)

            def exercise(worker: int) -> list[str]:
                errors: list[str] = []
                start.wait(timeout=5)
                try:
                    for index in range(iterations):
                        conversation_id = db.create_conversation()
                        db.add_message(conversation_id, "user", f"worker-{worker}-message-{index}")
                        task_id = db.create_task(conversation_id)
                        db.update_task(task_id, "SUCCEEDED")
                        task = db.get_task(task_id)
                        messages = db.get_messages(conversation_id)
                        recent = db.get_recent_messages(conversation_id, 10)
                        conversations = db.list_conversations(limit=workers * iterations)
                        db.set_setting(f"worker-{worker}", str(index))
                        setting = db.get_setting(f"worker-{worker}")
                        db.add_audit("storage_thread_safety_probe", {"worker": worker, "index": index})
                        if not task or task["status"] != "SUCCEEDED":
                            errors.append(f"task status mismatch for worker {worker}, index {index}")
                        if len(messages) != 1 or len(recent) != 1:
                            errors.append(f"message count mismatch for worker {worker}, index {index}")
                        if not conversations or setting != str(index):
                            errors.append(f"read result mismatch for worker {worker}, index {index}")
                except Exception as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                return errors

            try:
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    results = list(pool.map(exercise, range(workers)))
                flattened = [error for result in results for error in result]
                self.assertEqual(flattened, [])
                self.assertEqual(
                    db.connection.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
                    workers * iterations,
                )
                self.assertEqual(
                    db.connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
                    workers * iterations,
                )
                self.assertEqual(
                    db.connection.execute("SELECT COUNT(*) FROM tasks WHERE status = 'SUCCEEDED'").fetchone()[0],
                    workers * iterations,
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
