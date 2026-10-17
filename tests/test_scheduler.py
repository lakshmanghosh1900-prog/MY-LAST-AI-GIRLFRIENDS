from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Lock

from my_last_ai_girlfriends.scheduler import SchedulerError, validate_schedule
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService
from my_last_ai_girlfriends.storage import Database

from test_budget_service import FailingProvider, make_config


class SchedulerTests(unittest.TestCase):
    def test_schedule_requires_timezone_and_normalizes_to_utc(self):
        with self.assertRaises(SchedulerError):
            validate_schedule("Reminder", "hello", "2030-01-01T12:00:00", 1000)
        spec = validate_schedule("Reminder", "hello", "2030-01-01T12:00:00+02:00", 1000)
        self.assertTrue(spec.run_at.endswith("Z"))

    def test_due_schedule_runs_once_and_persists_result(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            conversation = service.create_conversation()
            schedule = service.create_schedule(conversation, "Say hello", "scheduled hello", "2020-01-01T00:00:00Z")
            first = service.run_due_schedules("2025-01-01T00:00:00Z")
            self.assertEqual(first[0]["status"], "SUCCEEDED")
            self.assertEqual(service.db.get_schedule(schedule["id"])["status"], "COMPLETED")
            second = service.run_due_schedules("2025-01-01T00:00:00Z")
            self.assertEqual(second, [])
            self.assertTrue(any(item["content"] == "scheduled hello" for item in service.conversation(conversation)["messages"]))
            service.close()

    def test_pending_schedule_run_claim_is_atomic(self):
        with tempfile.TemporaryDirectory() as raw:
            db = Database(Path(raw) / "scheduler.sqlite3")
            db.initialize()
            conversation = db.create_conversation()
            schedule = db.create_schedule(conversation, "Claim me", "hello", "2020-01-01T00:00:00Z")
            run = db.create_schedule_run(schedule["id"])
            barrier = Barrier(2)

            def claim() -> dict | None:
                barrier.wait(timeout=3)
                return db.claim_schedule_run(run["id"])

            with ThreadPoolExecutor(max_workers=2) as pool:
                claims = list(pool.map(lambda _: claim(), range(2)))

            self.assertEqual(sum(item is not None for item in claims), 1)
            self.assertEqual(db.get_schedule_run(run["id"])["status"], "RUNNING")
            db.close()

    def test_concurrent_due_schedulers_execute_schedule_once(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            conversation = service.create_conversation()
            schedule = service.create_schedule(conversation, "Once", "scheduled hello", "2020-01-01T00:00:00Z")
            original_create = service.db.create_schedule_run
            create_barrier = Barrier(2)

            def synchronized_create(schedule_id: str) -> dict:
                result = original_create(schedule_id)
                create_barrier.wait(timeout=3)
                return result

            original_handle = service.handle_message
            calls: list[str] = []
            calls_lock = Lock()

            def tracked_handle(conversation_id: str, content: str):
                with calls_lock:
                    calls.append(content)
                return original_handle(conversation_id, content)

            service.db.create_schedule_run = synchronized_create
            service.handle_message = tracked_handle
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: service.run_due_schedules("2025-01-01T00:00:00Z"), range(2)))
            finally:
                service.db.create_schedule_run = original_create
                service.handle_message = original_handle

            self.assertEqual(len(calls), 1)
            self.assertEqual(service.db.get_schedule(schedule["id"])["status"], "COMPLETED")
            self.assertEqual(service.db.connection.execute("SELECT COUNT(*) FROM schedule_runs").fetchone()[0], 1)
            self.assertEqual(service.db.get_schedule_run(results[0][0]["id"])["status"], "SUCCEEDED")
            service.close()

    def test_failed_schedule_run_is_terminal_and_not_retried(self):
        with tempfile.TemporaryDirectory() as raw:
            provider = FailingProvider()
            service = MyLastAIGirlfriendsService(
                make_config(Path(raw), mode="real", allow_remote=True),
                provider=provider,
            )
            conversation = service.create_conversation()
            schedule = service.create_schedule(conversation, "Try once", "scheduled failure", "2020-01-01T00:00:00Z")
            service.set_remote_consent(True)

            first = service.run_due_schedules("2025-01-01T00:00:00Z")
            second = service.run_due_schedules("2025-01-01T00:00:00Z")

            self.assertEqual(first[0]["status"], "FAILED")
            self.assertEqual(first[0]["reason"], "NEEDS_RECONCILIATION")
            self.assertEqual(second, first)
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(service.db.get_schedule(schedule["id"])["status"], "SCHEDULED")
            service.close()

    def test_cancelled_schedule_does_not_run(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            conversation = service.create_conversation()
            schedule = service.create_schedule(conversation, "Cancel me", "should not run", "2020-01-01T00:00:00Z")
            self.assertTrue(service.cancel_schedule(schedule["id"]))
            self.assertEqual(service.run_due_schedules("2025-01-01T00:00:00Z"), [])
            self.assertEqual(service.conversation(conversation)["messages"], [])
            service.close()


if __name__ == "__main__":
    unittest.main()
