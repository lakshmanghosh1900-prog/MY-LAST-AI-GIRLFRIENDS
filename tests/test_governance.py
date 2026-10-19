from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from my_last_ai_girlfriends.governance import GovernanceError
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService
from my_last_ai_girlfriends.storage import Database

from test_budget_service import make_config


class GovernanceTests(unittest.TestCase):
    def test_device_revocation_and_connector_scope(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            device = service.enroll_device("phone", "device-proof")
            self.assertEqual(service.list_devices()[0]["status"], "ENROLLED")
            self.assertTrue(service.verify_device(device["id"], "device-proof"))
            self.assertFalse(service.verify_device(device["id"], "wrong-proof"))
            diagnostics = service.device_diagnostics(device["id"])
            self.assertTrue(diagnostics["replay_protected"])
            self.assertFalse(diagnostics["encrypted"])
            challenge = service.create_device_pairing_challenge(device["id"])
            self.assertTrue(service.verify_device_pairing_challenge(device["id"], challenge["id"], challenge["challenge"], "device-proof"))
            self.assertFalse(service.verify_device_pairing_challenge(device["id"], challenge["id"], challenge["challenge"], "device-proof"))
            with self.assertRaisesRegex(GovernanceError, "between 30 and 900"):
                service.create_device_pairing_challenge(device["id"], ttl_seconds=10)
            self.assertTrue(service.revoke_device(device["id"]))
            self.assertFalse(service.verify_device(device["id"], "device-proof"))
            connector = service.register_connector("approved-later", "https://example.com/mcp", "read:calendar")
            self.assertEqual(connector["status"], "DRAFT")
            self.assertTrue(service.transition_connector(connector["id"], "APPROVED"))
            self.assertTrue(service.transition_connector(connector["id"], "REVOKED"))
            with self.assertRaisesRegex(GovernanceError, "revoked connectors cannot be reactivated"):
                service.transition_connector(connector["id"], "APPROVED")
            self.assertEqual(service.db.get_connector(connector["id"])["status"], "REVOKED")
            with self.assertRaisesRegex(GovernanceError, "credential-free HTTPS"):
                service.register_connector("unsafe", "http://example.com/mcp", "read:calendar")
            with self.assertRaisesRegex(GovernanceError, "port 443"):
                service.register_connector("bad-port", "https://example.com:bad/mcp", "read:calendar")
            service.close()

    def test_skills_require_review_and_unsafe_capabilities_are_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            skill = service.create_skill("summarize", "1.0.0", "local-test", ["read-only-text"])
            with self.assertRaisesRegex(GovernanceError, "reviewed"):
                service.transition_skill(skill["id"], "APPROVED")
            self.assertTrue(service.transition_skill(skill["id"], "REVIEW"))
            self.assertTrue(service.transition_skill(skill["id"], "APPROVED"))
            with self.assertRaisesRegex(GovernanceError, "arbitrary code"):
                service.create_skill("unsafe", "1.0.0", "unknown", ["code.execute"])
            service.close()

    def test_approvals_are_records_and_consumption_is_disabled(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            approval = service.create_approval("calendar.write", {"title": "demo"}, "2030-01-01T00:00:00Z")
            self.assertTrue(approval["nonce"])
            self.assertTrue(service.transition_approval(approval["id"], "APPROVED", "owner-session"))
            with self.assertRaisesRegex(GovernanceError, "disabled"):
                service.transition_approval(approval["id"], "CONSUMED")
            with self.assertRaisesRegex(GovernanceError, "future"):
                service.create_approval("calendar.write", {"title": "expired"}, "2000-01-01T00:00:00Z")
            service.close()

    def test_approval_expiry_requires_timezone_and_normalizes_to_utc(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            with self.assertRaisesRegex(GovernanceError, "include a timezone"):
                service.create_approval("local.schedule.create", {}, "2030-01-01T00:00:00")

            parameters = {"conversation_id": "unused", "title": "reminder", "prompt": "hello", "run_at": "2030-01-01T00:00:00Z"}
            approval = service.create_approval(
                "local.schedule.create",
                parameters,
                "2030-01-01T02:00:00+02:00",
            )
            self.assertEqual(approval["expires_at"], "2030-01-01T00:00:00.000000Z")
            service.transition_approval(approval["id"], "APPROVED", "owner-session")

            # Guard against historical/corrupt records with a naive timestamp.
            with service.db.transaction():
                service.db.connection.execute(
                    "UPDATE approvals SET expires_at = ? WHERE id = ?",
                    ("2030-01-01T00:00:00", approval["id"]),
                )
            with self.assertRaisesRegex(GovernanceError, "include a timezone"):
                service.execute_approved_action(approval["id"], parameters, approval["nonce"])
            service.close()

    def test_expired_approval_cannot_be_approved(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            expires_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
            approval = service.create_approval("local.schedule.create", {}, expires_at)
            expired_local = (datetime.now(timezone.utc) - timedelta(minutes=1)).astimezone(
                timezone(timedelta(hours=14))
            ).isoformat(timespec="microseconds")
            with service.db.transaction():
                service.db.connection.execute(
                    "UPDATE approvals SET expires_at = ? WHERE id = ?",
                    (expired_local, approval["id"]),
                )
            with self.assertRaisesRegex(GovernanceError, "Expired approvals cannot be approved"):
                service.transition_approval(approval["id"], "APPROVED", "owner-session")
            self.assertEqual(service.db.get_approval(approval["id"])["status"], "PENDING")
            service.close()

    def test_revoked_or_consumed_approval_cannot_be_reapproved(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            expires_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
            revoked = service.create_approval("local.schedule.create", {}, expires_at)
            self.assertTrue(service.transition_approval(revoked["id"], "REVOKED"))
            with self.assertRaisesRegex(GovernanceError, "cannot transition"):
                service.transition_approval(revoked["id"], "APPROVED")

            conversation = service.create_conversation()
            params = {"conversation_id": conversation, "title": "once", "prompt": "once", "run_at": "2030-01-01T00:00:00Z"}
            consumed = service.create_approval("local.schedule.create", params, expires_at)
            service.transition_approval(consumed["id"], "APPROVED", "owner-session")
            service.execute_approved_action(consumed["id"], params, consumed["nonce"])
            with self.assertRaisesRegex(GovernanceError, "cannot transition"):
                service.transition_approval(consumed["id"], "APPROVED")
            self.assertEqual(service.db.get_approval(consumed["id"])["status"], "CONSUMED")
            service.close()

    def test_approved_local_schedule_action_is_single_use(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            conversation = service.create_conversation()
            parameters = {"conversation_id": conversation, "title": "approved reminder", "prompt": "scheduled", "run_at": "2020-01-01T00:00:00Z"}
            approval = service.create_approval("local.schedule.create", parameters, "2030-01-02T00:00:00Z")
            service.transition_approval(approval["id"], "APPROVED", "owner-session")
            result = service.execute_approved_action(approval["id"], parameters, approval["nonce"])
            self.assertEqual(result["status"], "EXECUTED")
            self.assertEqual(result["schedule"]["recurrence"], "once")
            self.assertEqual(result["schedule"]["next_run_at"], "2020-01-01T00:00:00.000000Z")
            with self.assertRaisesRegex(GovernanceError, "approved"):
                service.execute_approved_action(approval["id"], parameters, approval["nonce"])
            self.assertEqual(service.list_schedules(conversation)[0]["id"], result["schedule"]["id"])
            runs = service.run_due_schedules("2025-01-01T00:00:00Z")
            self.assertEqual(len(runs), 1)
            self.assertEqual(runs[0]["status"], "SUCCEEDED")
            self.assertEqual(service.run_due_schedules("2025-01-01T00:00:00Z"), [])
            self.assertTrue(any(item["content"] == "scheduled" for item in service.conversation(conversation)["messages"]))
            service.close()

    def test_storage_rechecks_expiry_as_instant_inside_approval_transaction(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            conversation = service.create_conversation()
            expires_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
            approval = service.create_approval(
                "local.schedule.create",
                {"conversation_id": conversation, "title": "expired", "prompt": "must not run", "run_at": "2030-01-01T00:00:00Z"},
                expires_at,
            )
            service.transition_approval(approval["id"], "APPROVED", "owner-session")

            # Represent an expired instant in a +14:00 timezone. Its local
            # timestamp sorts after UTC's timestamp even though the instant is past.
            expired_local = (datetime.now(timezone.utc) - timedelta(minutes=1)).astimezone(
                timezone(timedelta(hours=14))
            ).isoformat(timespec="microseconds")
            with service.db.transaction():
                service.db.connection.execute(
                    "UPDATE approvals SET expires_at = ? WHERE id = ?",
                    (expired_local, approval["id"]),
                )

            with self.assertRaisesRegex(ValueError, "not executable"):
                service.db.execute_local_schedule_approval(
                    approval["id"], conversation, "expired", "must not run", "2030-01-01T00:00:00.000000Z"
                )
            schedules = service.db.connection.execute(
                "SELECT COUNT(*) FROM schedules WHERE conversation_id = ?", (conversation,)
            ).fetchone()[0]
            self.assertEqual(schedules, 0)
            service.close()

    def test_bounded_agent_pipeline_does_not_expand_capabilities(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            result = service.run_agents("prepare a local plan")
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(result["execution_mode"], "local_deterministic")
            self.assertFalse(result["ai_generated"])
            self.assertEqual(result["capability_set"], ["read-only-file", "public-fetch"])
            stored = service.db.connection.execute("SELECT id FROM agent_runs WHERE id = ?", (result["run_id"],)).fetchone()
            self.assertIsNotNone(stored)
            listed = service.list_agent_runs()[0]
            self.assertEqual(listed["id"], result["run_id"])
            self.assertEqual(listed["execution_mode"], "local_deterministic")
            self.assertFalse(listed["ai_generated"])
            service.close()


if __name__ == "__main__":
    unittest.main()
