from __future__ import annotations

import tempfile
import unittest
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

    def test_bounded_agent_pipeline_does_not_expand_capabilities(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            result = service.run_agents("prepare a local plan")
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(result["capability_set"], ["read-only-file", "public-fetch"])
            stored = service.db.connection.execute("SELECT id FROM agent_runs WHERE id = ?", (result["run_id"],)).fetchone()
            self.assertIsNotNone(stored)
            self.assertEqual(service.list_agent_runs()[0]["id"], result["run_id"])
            service.close()


if __name__ == "__main__":
    unittest.main()
