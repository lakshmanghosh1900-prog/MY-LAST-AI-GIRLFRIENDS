from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier, Event, Lock, Thread

from my_last_ai_girlfriends.scheduler import SchedulerError, SchedulerWorker, next_run_at, validate_schedule
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService
from my_last_ai_girlfriends.storage import Database

from unittest.mock import patch

from test_budget_service import FailingProvider, make_config


class SchedulerTests(unittest.TestCase):
    def test_scheduler_worker_starts_ticks_and_stops(self):
        event = Barrier(2)
        calls = []

        def tick():
            calls.append(True)
            event.wait(timeout=2)

        worker = SchedulerWorker(tick, interval_seconds=1)
        worker.start()
        event.wait(timeout=2)
        self.assertTrue(worker.running)
        worker.stop()
        self.assertFalse(worker.running)
        self.assertGreaterEqual(len(calls), 1)

    def test_concurrent_start_calls_create_only_one_worker(self):
        release_thread_start = Event()
        thread_start_entered = Event()
        created_threads = []

        class DelayedStartThread(Thread):
            def start(self):
                created_threads.append(self)
                thread_start_entered.set()
                if not release_thread_start.wait(timeout=3):
                    raise RuntimeError("test did not release delayed thread start")
                super().start()

        worker = SchedulerWorker(lambda: None, interval_seconds=1)
        with patch("my_last_ai_girlfriends.scheduler.Thread", DelayedStartThread):
            first = Thread(target=worker.start)
            first.start()
            self.assertTrue(thread_start_entered.wait(timeout=1))
            second_entered = Event()

            def second_start():
                second_entered.set()
                worker.start()

            second = Thread(target=second_start)
            second.start()
            self.assertTrue(second_entered.wait(timeout=1))
            release_thread_start.set()
            first.join(timeout=2)
            second.join(timeout=2)
            try:
                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertEqual(len(created_threads), 1)
                self.assertTrue(worker.running)
            finally:
                worker.stop(timeout=2)

    def test_worker_stop_timeout_keeps_live_thread_reference(self):
        started = Event()
        release = Event()
        finished = Event()

        def tick():
            started.set()
            release.wait(timeout=2)
            finished.set()

        worker = SchedulerWorker(tick, interval_seconds=1)
        worker.start()
        self.assertTrue(started.wait(timeout=1))
        with self.assertRaisesRegex(SchedulerError, "before timeout"):
            worker.stop(timeout=0.01)
        self.assertTrue(worker.running)

        release.set()
        self.assertTrue(finished.wait(timeout=1))
        worker.stop(timeout=1)
        self.assertFalse(worker.running)

    def test_error_reporter_failure_does_not_kill_scheduler_loop(self):
        second_tick = Event()
        calls = []

        def tick():
            calls.append("tick")
            if len(calls) >= 2:
                second_tick.set()
            raise RuntimeError("expected tick failure")

        def broken_reporter(_exc):
            raise RuntimeError("reporter failed")

        worker = SchedulerWorker(tick, interval_seconds=1, on_error=broken_reporter)
        worker.start()
        try:
            self.assertTrue(second_tick.wait(timeout=3))
            self.assertTrue(worker.running)
        finally:
            worker.stop(timeout=1)

    def test_worker_stop_rejects_invalid_timeout(self):
        worker = SchedulerWorker(lambda: None)
        for timeout in (-1, float("nan"), float("inf"), True):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(SchedulerError, "finite non-negative"):
                    worker.stop(timeout=timeout)

    def test_scheduler_worker_rejects_invalid_interval(self):
        with self.assertRaises(SchedulerError):
            SchedulerWorker(lambda: None, interval_seconds=0)

    def test_schedule_requires_timezone_and_normalizes_to_utc(self):
        with self.assertRaises(SchedulerError):
            validate_schedule("Reminder", "hello", "2030-01-01T12:00:00", 1000)
        spec = validate_schedule("Reminder", "hello", "2030-01-01T12:00:00+02:00", 1000)
        self.assertTrue(spec.run_at.endswith("Z"))

    def test_recurring_schedule_uses_fixed_utc_intervals(self):
        spec = validate_schedule("Daily", "hello", "2030-01-01T12:00:00+02:00", 1000, "daily")
        self.assertEqual(spec.recurrence, "daily")
        self.assertEqual(spec.run_at, "2030-01-01T10:00:00.000000Z")
        self.assertEqual(next_run_at(spec.run_at, spec.recurrence), "2030-01-02T10:00:00.000000Z")
        with self.assertRaises(SchedulerError):
            validate_schedule("Bad", "hello", "2030-01-01T00:00:00Z", 1000, "monthly")

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

    def test_cancelled_between_due_lookup_and_run_creation_is_skipped(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            conversation = service.create_conversation()
            first = service.create_schedule(conversation, "First", "first scheduled prompt", "2020-01-01T00:00:00Z")
            second = service.create_schedule(conversation, "Second", "second scheduled prompt", "2020-01-01T00:00:00Z")
            original_create = service.db.create_schedule_run
            create_calls: list[str] = []

            def cancel_before_create(schedule_id: str) -> dict:
                create_calls.append(schedule_id)
                if len(create_calls) == 1:
                    self.assertTrue(service.db.cancel_schedule(schedule_id))
                return original_create(schedule_id)

            service.db.create_schedule_run = cancel_before_create
            try:
                results = service.run_due_schedules("2025-01-01T00:00:00Z")
            finally:
                service.db.create_schedule_run = original_create

            self.assertEqual(len(create_calls), 2)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "SUCCEEDED")
            cancelled_id = create_calls[0]
            self.assertEqual(service.db.get_schedule(cancelled_id)["status"], "CANCELLED")
            cancelled_prompt = first["prompt"] if cancelled_id == first["id"] else second["prompt"]
            messages = service.conversation(conversation)["messages"]
            self.assertFalse(any(item["content"] == cancelled_prompt for item in messages))
            service.close()

    def test_daily_schedule_survives_restart_and_advances_occurrence(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            service = MyLastAIGirlfriendsService(make_config(root))
            conversation = service.create_conversation()
            schedule = service.create_schedule(conversation, "Daily hello", "daily hello", "2020-01-01T00:00:00Z", "daily")
            first = service.run_due_schedules("2020-01-01T00:00:01Z")
            self.assertEqual(first[0]["status"], "SUCCEEDED")
            after_first = service.db.get_schedule(schedule["id"])
            self.assertEqual(after_first["status"], "SCHEDULED")
            self.assertEqual(after_first["next_run_at"], "2020-01-02T00:00:00.000000Z")
            service.close()

            restarted = MyLastAIGirlfriendsService(make_config(root))
            self.assertEqual(restarted.run_due_schedules("2020-01-01T23:59:59Z"), [])
            second = restarted.run_due_schedules("2020-01-02T00:00:01Z")
            self.assertEqual(second[0]["status"], "SUCCEEDED")
            self.assertEqual(restarted.db.get_schedule(schedule["id"])["next_run_at"], "2020-01-03T00:00:00.000000Z")
            self.assertEqual(restarted.db.connection.execute("SELECT COUNT(*) FROM schedule_runs").fetchone()[0], 2)
            restarted.close()

    def test_recurring_failure_advances_without_automatic_retry(self):
        with tempfile.TemporaryDirectory() as raw:
            provider = FailingProvider()
            service = MyLastAIGirlfriendsService(make_config(Path(raw), mode="real", allow_remote=True), provider=provider)
            service.set_remote_consent(True)
            conversation = service.create_conversation()
            schedule = service.create_schedule(conversation, "Hourly failure", "hourly failure", "2020-01-01T00:00:00Z", "hourly")
            first = service.run_due_schedules("2020-01-01T00:00:01Z")
            self.assertEqual(first[0]["status"], "FAILED")
            self.assertEqual(service.db.get_schedule(schedule["id"])["next_run_at"], "2020-01-01T01:00:00.000000Z")
            self.assertEqual(service.run_due_schedules("2020-01-01T00:30:00Z"), [])
            self.assertEqual(len(provider.calls), 1)
            service.close()


if __name__ == "__main__":
    unittest.main()
