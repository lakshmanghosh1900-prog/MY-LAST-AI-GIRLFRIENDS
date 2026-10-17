from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from my_last_ai_girlfriends.scheduler import SchedulerError, validate_schedule
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService

from test_budget_service import make_config


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
