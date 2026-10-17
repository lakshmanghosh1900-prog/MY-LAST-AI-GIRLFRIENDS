from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import unittest
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.config import Config, ConfigError, diagnose_environment, load_environment, token_status
from my_last_ai_girlfriends.main import main
from my_last_ai_girlfriends.providers import GeminiProvider, ProviderError, build_chat_completions_url


class _Response:
    status = 200

    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1):
        return self.payload


class ConfigurationAndProviderTests(unittest.TestCase):
    def test_process_environment_wins_and_conflict_is_diagnosed_without_values(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text("MLAG_AUTH_TOKEN=" + "F" * 48 + "\nMLAG_MODE=offline\n", encoding="utf-8")
            report = load_environment(path, {"MLAG_AUTH_TOKEN": "P" * 48, "MLAG_MODE": "real"})
            self.assertEqual(report.source["MLAG_AUTH_TOKEN"], "process")
            self.assertIn("MLAG_AUTH_TOKEN", report.conflicts)
            diagnosis = diagnose_environment(report)
            self.assertEqual(diagnosis["token_status"], "valid")
            self.assertNotIn("P" * 48, str(diagnosis))

    def test_legacy_dotenv_values_are_explicit_compatibility_only(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text("JARVIS_AUTH_TOKEN=" + "L" * 48 + "\n", encoding="utf-8")
            report = load_environment(path, {})
            self.assertEqual(report.values["MLAG_AUTH_TOKEN"], "L" * 48)
            self.assertEqual(report.source["MLAG_AUTH_TOKEN"], "dotenv-legacy")

    def test_new_and_legacy_values_in_one_source_are_reported_as_conflicts(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / ".env"
            path.write_text(
                "MLAG_AUTH_TOKEN=" + "N" * 48 + "\n"
                + "JARVIS_AUTH_TOKEN=" + "L" * 48 + "\n",
                encoding="utf-8",
            )
            report = load_environment(path, {})
            self.assertEqual(report.values["MLAG_AUTH_TOKEN"], "N" * 48)
            self.assertIn("MLAG_AUTH_TOKEN", report.conflicts)

    def test_real_mode_requires_a_credential_free_https_provider_url(self):
        base = {
            "MLAG_AUTH_TOKEN": "T" * 48,
            "MLAG_MODE": "real",
            "MLAG_GEMINI_API_KEY": "K" * 40,
        }
        for url in ("http://example.test/openai/", "https://user:pass@example.test/openai/", "not-a-url"):
            with self.subTest(url=url):
                with self.assertRaises(ConfigError):
                    Config.from_report(load_environment(Path("missing.env"), {**base, "MLAG_PROVIDER_BASE_URL": url}))

    def test_placeholder_and_short_tokens_are_not_accepted(self):
        self.assertEqual(token_status("deleted"), "invalid-placeholder")
        self.assertEqual(token_status("short"), "too-short")
        with self.assertRaises(ConfigError):
            Config.from_report(load_environment(Path("missing.env"), {"MLAG_AUTH_TOKEN": "deleted"}))

    def test_token_rotation_preserves_nonsecret_configuration_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".env.example").write_text("MLAG_AUTH_TOKEN=replace-with-a-fresh-random-token\nMLAG_MODE=real\nMLAG_GEMINI_API_KEY=private-value\n", encoding="utf-8")
            (root / ".env").write_text("MLAG_AUTH_TOKEN=" + "A" * 48 + "\nMLAG_MODE=real\nMLAG_GEMINI_API_KEY=private-value\n", encoding="utf-8")
            previous = os.getcwd()
            try:
                os.chdir(root)
                self.assertEqual(main(["generate-token"]), 0)
            finally:
                os.chdir(previous)
            content = (root / ".env").read_text(encoding="utf-8")
            self.assertIn("MLAG_MODE=real", content)
            self.assertIn("MLAG_GEMINI_API_KEY=private-value", content)
            self.assertNotIn("MLAG_AUTH_TOKEN=" + "A" * 48, content)
            self.assertTrue(list(root.glob(".env.before-token-rotation.*")))

    def test_gemini_endpoint_is_appended_once(self):
        base = "https://generativelanguage.googleapis.com/v1beta/openai/"
        self.assertEqual(build_chat_completions_url(base), base.rstrip("/") + "/chat/completions")
        self.assertEqual(build_chat_completions_url(base.rstrip("/") + "/chat/completions"), base.rstrip("/") + "/chat/completions")

    def test_gemini_request_uses_bearer_and_real_response(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response({"id": "req-1", "model": "gemini-3.8-flash", "choices": [{"message": {"content": "real answer"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})

        with patch("urllib.request.urlopen", fake_urlopen):
            result = provider.complete([{"role": "user", "content": "hello"}], 128, 7)
        self.assertEqual(captured["url"], "https://example.test/v1beta/openai/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer secret-key")
        self.assertEqual(captured["body"]["model"], "gemini-3.8-flash")
        self.assertEqual(captured["timeout"], 7)
        self.assertTrue(result.ai_generated)
        self.assertTrue(provider.status()["connected"])

    def test_gemini_malformed_response_fails_without_demo_fallback(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        with patch("urllib.request.urlopen", lambda *_args, **_kwargs: _Response({"choices": []})):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([{"role": "user", "content": "hello"}], 128, 7)
        self.assertEqual(caught.exception.code, "PROVIDER_SCHEMA")

    def test_gemini_rejects_empty_and_unsupported_tool_outputs(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        for payload, code in (
            ({"choices": [{"message": {"content": ""}}]}, "PROVIDER_EMPTY_OUTPUT"),
            ({"choices": [{"message": {"content": "answer", "tool_calls": [{"id": "x"}]}}]}, "PROVIDER_TOOL_CALL_REJECTED"),
        ):
            with self.subTest(code=code), patch("urllib.request.urlopen", lambda *_args, **_kwargs: _Response(payload)):
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([{"role": "user", "content": "hello"}], 128, 7)
                self.assertEqual(caught.exception.code, code)

    def test_gemini_rejects_oversized_output_and_resets_connection_status(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        payload = {"choices": [{"message": {"content": "x" * 2049}}], "usage": {"prompt_tokens": 1, "completion_tokens": 999}}
        with patch("urllib.request.urlopen", lambda *_args, **_kwargs: _Response(payload)):
            with self.assertRaisesRegex(ProviderError, "output bound"):
                provider.complete([{"role": "user", "content": "hello"}], 256, 7)
        self.assertFalse(provider.status()["connected"])
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(ProviderError):
                provider.complete([{"role": "user", "content": "hello"}], 128, 7)
        self.assertFalse(provider.status()["connected"])

    def test_gemini_classifies_auth_quota_and_network_failures_without_retry(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        for status, code, unknown in (
            (401, "PROVIDER_AUTHENTICATION", False),
            (429, "PROVIDER_RATE_LIMIT", True),
            (503, "PROVIDER_HTTP_ERROR", True),
        ):
            def raise_http_error(*_args, _status=status, **_kwargs):
                raise urllib.error.HTTPError("https://example.test", _status, "provider", {}, None)

            with self.subTest(status=status), patch("urllib.request.urlopen", raise_http_error):
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([{"role": "user", "content": "hello"}], 128, 7)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.usage_unknown, unknown)

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([{"role": "user", "content": "hello"}], 128, 7)
        self.assertEqual(caught.exception.code, "PROVIDER_TIMEOUT_OR_NETWORK")
        self.assertTrue(caught.exception.usage_unknown)


if __name__ == "__main__":
    unittest.main()
