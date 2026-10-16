from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from jarvis_omega.config import Config
from jarvis_omega.budget import BudgetLedger
from jarvis_omega.providers import FakeProvider
from jarvis_omega.service import JarvisService
from jarvis_omega.storage import Database


def make_config(root: Path, provider: str = "fake", allow_remote: bool = False) -> Config:
    env = {
        "JARVIS_AUTH_TOKEN": "T" * 48,
        "JARVIS_HOST": "127.0.0.1",
        "JARVIS_PORT": "8787",
        "JARVIS_PROVIDER": provider,
        "JARVIS_MODEL": "test-model",
        "JARVIS_PROVIDER_URL": "https://provider.example/v1" if provider != "fake" else "",
        "JARVIS_PROVIDER_API_KEY": "K" * 40 if provider != "fake" else "",
        "JARVIS_ALLOW_REMOTE_PERSONAL_DATA": str(allow_remote).lower(),
        "JARVIS_DATA_DIR": str(root / "data"),
        "JARVIS_ALLOWED_ROOT": str(root / "workspace"),
        "JARVIS_MONTHLY_BUDGET_INR": "3500",
        "JARVIS_FX_INR_PER_USD": "95",
        "JARVIS_MAX_INPUT_TOKENS": "12000",
        "JARVIS_MAX_OUTPUT_TOKENS": "512",
    }
    return Config.from_env(env)


class BudgetAndServiceTests(unittest.TestCase):
    def test_concurrent_reservations_cannot_exceed_limit(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            db = Database(root / "budget.sqlite3")
            db.initialize()
            conversation = db.create_conversation()
            tasks = [db.create_task(conversation) for _ in range(8)]
            ledger = BudgetLedger(db, monthly_limit_usd_micros=1000)

            def reserve(task_id: str):
                return ledger.reserve(task_id, 600, task_id)

            with ThreadPoolExecutor(max_workers=8) as pool:
                reservations = list(pool.map(reserve, tasks))
            accepted = [item for item in reservations if item.accepted]
            self.assertEqual(len(accepted), 1)
            self.assertLessEqual(ledger.usage_usd_micros(), 1000)
            db.close()

    def test_service_persists_success_and_safe_stops_bad_inputs(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            config = make_config(root)
            (root / "workspace").mkdir(parents=True)
            (root / "workspace" / "notes.txt").write_text("Bengali note: শুভ সকাল", encoding="utf-8")
            service = JarvisService(config)
            conversation = service.create_conversation()

            success = service.handle_message(conversation, "hello Jarvis")
            self.assertEqual(success.status, "SUCCEEDED")
            stored = service.conversation(conversation)
            self.assertEqual([item["role"] for item in stored["messages"]], ["user", "assistant"])

            file_result = service.handle_message(conversation, "/file notes.txt")
            self.assertEqual(file_result.status, "SUCCEEDED")
            traversal = service.handle_message(conversation, "/file ../notes.txt")
            self.assertEqual(traversal.status, "SAFE_STOP")
            secret = service.handle_message(conversation, "my password is hunter2")
            self.assertEqual(secret.status, "SAFE_STOP")
            self.assertNotIn("hunter2", service.db.connection.execute("SELECT metadata_json FROM audit_events").fetchall().__str__())
            service.close()

    def test_lifecycle_stop_and_restart_is_explicit(self):
        with tempfile.TemporaryDirectory() as raw:
            service = JarvisService(make_config(Path(raw)))
            self.assertEqual(service.health()["state"], "READY")
            self.assertEqual(service.stop(), "STOPPED")
            with self.assertRaises(RuntimeError):
                service.create_conversation()
            self.assertEqual(service.start(), "READY")
            self.assertIsInstance(service.create_conversation(), str)
            service.close()


if __name__ == "__main__":
    unittest.main()
