from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from my_last_ai_girlfriends.budget import BudgetLedger
from my_last_ai_girlfriends.config import Config, load_environment
from my_last_ai_girlfriends.providers import Provider, ProviderError, ProviderResult
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService
from my_last_ai_girlfriends.storage import Database


def make_config(root: Path, mode: str = "offline", allow_remote: bool = False) -> Config:
    env = {
        "MLAG_AUTH_TOKEN": "T" * 48,
        "MLAG_HOST": "127.0.0.1",
        "MLAG_PORT": "8787",
        "MLAG_TRUSTED_HOSTS": "127.0.0.1,localhost",
        "MLAG_MODE": mode,
        "MLAG_PROVIDER": "gemini",
        "MLAG_MODEL": "gemini-3.8-flash",
        "MLAG_PROVIDER_BASE_URL": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "MLAG_GEMINI_API_KEY": "K" * 40 if mode == "real" else "",
        "MLAG_ALLOW_REMOTE_PERSONAL_DATA": str(allow_remote).lower(),
        "MLAG_DATA_DIR": str(root / "data"),
        "MLAG_ALLOWED_ROOT": str(root / "workspace"),
        "MLAG_MONTHLY_BUDGET_INR": "3500",
        "MLAG_FX_INR_PER_USD": "95",
        "MLAG_INPUT_PRICE_USD_PER_MILLION": "0.75",
        "MLAG_OUTPUT_PRICE_USD_PER_MILLION": "3.75",
        "MLAG_MAX_INPUT_TOKENS": "12000",
        "MLAG_MAX_OUTPUT_TOKENS": "512",
        "MLAG_MAX_CONTEXT_MESSAGES": "4",
    }
    return Config.from_report(load_environment(Path(root / "missing.env"), env))


class RecordingProvider(Provider):
    name = "gemini"
    model = "gemini-3.8-flash"
    ai_generated = True

    def __init__(self):
        self.calls = []

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        return input_tokens + output_tokens

    def complete(self, messages, max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        del max_output_tokens, timeout_seconds
        messages = list(messages)
        self.calls.append(messages)
        return ProviderResult("real reply", self.name, self.model, 10, 3, "test-request", 1, True)


class FailingProvider(RecordingProvider):
    def complete(self, messages, max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        self.calls.append(list(messages))
        raise ProviderError("PROVIDER_RATE_LIMIT", "rate limited", usage_unknown=True)


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

    def test_offline_demo_is_explicit_and_context_is_conversation_local(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            service = MyLastAIGirlfriendsService(make_config(root))
            first = service.create_conversation()
            second = service.create_conversation()
            first_result = service.handle_message(first, "বাংলায় শুভ সকাল")
            self.assertEqual(first_result.status, "SUCCEEDED")
            self.assertFalse(first_result.ai_generated)
            self.assertIn("Offline demo", first_result.message)
            service.handle_message(first, "follow-up in English")
            service.handle_message(second, "isolated conversation")
            second_messages = service.conversation(second)["messages"]
            self.assertTrue(all("follow-up" not in item["content"] for item in second_messages))
            service.close()

    def test_file_preview_is_not_sent_as_fake_semantic_summary(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir(parents=True)
            (root / "workspace" / "notes.txt").write_text("Bengali note: শুভ সকাল", encoding="utf-8")
            service = MyLastAIGirlfriendsService(make_config(root))
            conversation = service.create_conversation()
            result = service.handle_message(conversation, "/file notes.txt")
            self.assertEqual(result.status, "SUCCEEDED")
            self.assertFalse(result.ai_generated)
            self.assertIn("Offline demo preview", result.message)
            service.close()

    def test_prohibited_input_is_not_persisted_raw(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            service = MyLastAIGirlfriendsService(make_config(root))
            conversation = service.create_conversation()
            result = service.handle_message(conversation, "my password is hunter2")
            self.assertEqual(result.status, "SAFE_STOP")
            self.assertNotIn("hunter2", str(service.conversation(conversation)))
            service.close()

    def test_lifecycle_stop_and_restart_is_explicit(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            self.assertEqual(service.health()["state"], "READY")
            self.assertEqual(service.stop(), "STOPPED")
            with self.assertRaises(RuntimeError):
                service.create_conversation()
            self.assertEqual(service.start(), "READY")
            self.assertIsInstance(service.create_conversation(), str)
            service.close()

    def test_real_context_is_bounded_chronological_and_current_message_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as raw:
            provider = RecordingProvider()
            service = MyLastAIGirlfriendsService(make_config(Path(raw), mode="real", allow_remote=True), provider=provider)
            service.set_remote_consent(True)
            conversation = service.create_conversation()
            service.handle_message(conversation, "first turn")
            service.handle_message(conversation, "second turn")
            second_call = provider.calls[-1]
            user_contents = [item["content"] for item in second_call if item["role"] == "user"]
            self.assertEqual(user_contents.count("second turn"), 1)
            self.assertIn("first turn", " ".join(user_contents))
            self.assertEqual(second_call[0]["role"], "system")
            service.close()

    def test_real_provider_failure_never_falls_back_to_offline_demo(self):
        with tempfile.TemporaryDirectory() as raw:
            provider = FailingProvider()
            service = MyLastAIGirlfriendsService(make_config(Path(raw), mode="real", allow_remote=True), provider=provider)
            service.set_remote_consent(True)
            conversation = service.create_conversation()
            result = service.handle_message(conversation, "ordinary personal chat")
            self.assertEqual(result.status, "NEEDS_RECONCILIATION")
            self.assertNotIn("Offline demo", result.message)
            self.assertEqual(len(provider.calls), 1)
            service.close()


if __name__ == "__main__":
    unittest.main()
