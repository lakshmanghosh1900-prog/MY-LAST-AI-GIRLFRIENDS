from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.request
import unittest
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.config import Config, ConfigError, diagnose_environment, load_environment, token_status
from my_last_ai_girlfriends.main import main
from my_last_ai_girlfriends.providers import GeminiProvider, OllamaProvider, ProviderError, _NoRedirectHandler, build_chat_completions_url


class _Response:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self.payload = json.dumps(payload).encode("utf-8")
        self.read_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit: int = -1):
        self.read_count += 1
        return self.payload if _limit < 0 else self.payload[:_limit]


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

    def test_doctor_readiness_matches_startup_provider_requirements(self):
        token = "T" * 48
        real_without_key = load_environment(
            Path("missing.env"), {"MLAG_AUTH_TOKEN": token, "MLAG_MODE": "real"}
        )
        missing_key_diagnosis = diagnose_environment(real_without_key)
        self.assertFalse(missing_key_diagnosis["ready"])
        self.assertIn("MLAG_GEMINI_API_KEY", missing_key_diagnosis["readiness_error"])

        real_with_key = load_environment(
            Path("missing.env"),
            {"MLAG_AUTH_TOKEN": token, "MLAG_MODE": "real", "MLAG_GEMINI_API_KEY": "K" * 40},
        )
        valid_diagnosis = diagnose_environment(real_with_key)
        self.assertTrue(valid_diagnosis["ready"])
        self.assertIsNone(valid_diagnosis["readiness_error"])

        unsupported = load_environment(
            Path("missing.env"),
            {"MLAG_AUTH_TOKEN": token, "MLAG_MODE": "real", "MLAG_PROVIDER": "unknown", "MLAG_GEMINI_API_KEY": "K" * 40},
        )
        unsupported_diagnosis = diagnose_environment(unsupported)
        self.assertFalse(unsupported_diagnosis["ready"])
        self.assertIn("MLAG_PROVIDER", unsupported_diagnosis["readiness_error"])

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
        for url in ("http://example.test/openai/", "https://user:pass@example.test/openai/", "https://[::1", "not-a-url"):
            with self.subTest(url=url):
                with self.assertRaises(ConfigError):
                    Config.from_report(load_environment(Path("missing.env"), {**base, "MLAG_PROVIDER_BASE_URL": url}))

    def test_ollama_local_provider_configuration_and_response(self):
        base = {"MLAG_AUTH_TOKEN": "T" * 48, "MLAG_MODE": "real", "MLAG_PROVIDER": "ollama", "MLAG_MODEL": "llama3.2"}
        config = Config.from_report(load_environment(Path("missing.env"), base))
        self.assertEqual(config.provider, "ollama")
        provider = OllamaProvider("http://127.0.0.1:11434", "llama3.2")
        with patch("my_last_ai_girlfriends.providers._open_without_redirects", lambda *_args, **_kwargs: _Response({"message": {"content": "local answer"}, "prompt_eval_count": 2, "eval_count": 3})):
            result = provider.complete([{"role": "user", "content": "hello"}], 128, 3)
        self.assertEqual(result.text, "local answer")
        self.assertTrue(provider.status()["local"])

    def test_decimal_configuration_rejects_non_finite_numbers(self):
        base = {"MLAG_AUTH_TOKEN": "T" * 48}
        cases = (
            ("MLAG_FX_INR_PER_USD", "NaN"),
            ("MLAG_FX_INR_PER_USD", "sNaN"),
            ("MLAG_MONTHLY_BUDGET_INR", "Infinity"),
            ("MLAG_INPUT_PRICE_USD_PER_MILLION", "-Infinity"),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ConfigError):
                    Config.from_report(load_environment(Path("missing.env"), {**base, key: value}))

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

    def test_provider_redirect_handler_blocks_cross_host_post_redirects(self):
        handler = _NoRedirectHandler()
        request = urllib.request.Request(
            "https://example.test/chat/completions",
            data=b'{"messages":[{"content":"private prompt"}]}',
            method="POST",
        )
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status=status):
                redirected = handler.redirect_request(
                    request,
                    None,
                    status,
                    "redirect",
                    {},
                    "https://attacker.test/collect",
                )
                self.assertIsNone(redirected)

    def test_providers_reject_non_success_responses_before_reading_body(self):
        gemini = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        gemini_response = _Response({"choices": [{"message": {"content": "redirect body"}}]}, status=302)
        with patch("my_last_ai_girlfriends.providers._open_without_redirects", return_value=gemini_response):
            with self.assertRaises(ProviderError) as caught:
                gemini.complete([{"role": "user", "content": "private prompt"}], 128, 7)
        self.assertEqual(caught.exception.code, "PROVIDER_HTTP_ERROR")
        self.assertEqual(gemini_response.read_count, 0)

        ollama = OllamaProvider("http://127.0.0.1:11434", "llama3.2")
        ollama_response = _Response({"message": {"content": "redirect body"}}, status=302)
        with patch("my_last_ai_girlfriends.providers._open_without_redirects", return_value=ollama_response):
            with self.assertRaises(ProviderError) as caught:
                ollama.complete([{"role": "user", "content": "private prompt"}], 128, 7)
        self.assertEqual(caught.exception.code, "LOCAL_PROVIDER_HTTP_ERROR")
        self.assertEqual(ollama_response.read_count, 0)
        self.assertFalse(ollama.status()["connected"])

    def test_ollama_rejects_negative_token_usage(self):
        provider = OllamaProvider("http://127.0.0.1:11434", "llama3.2")
        payloads = (
            {"message": {"content": "local answer"}, "prompt_eval_count": -1, "eval_count": 2},
            {"message": {"content": "local answer"}, "prompt_eval_count": 1, "eval_count": -2},
        )
        for payload in payloads:
            with self.subTest(payload=payload), patch(
                "my_last_ai_girlfriends.providers._open_without_redirects",
                lambda *_args, _payload=payload, **_kwargs: _Response(_payload),
            ):
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([{"role": "user", "content": "hello"}], 128, 3)
                self.assertEqual(caught.exception.code, "PROVIDER_SCHEMA")
                self.assertFalse(provider.status()["connected"])

    def test_ollama_rejects_oversized_response(self):
        provider = OllamaProvider("http://127.0.0.1:11434", "llama3.2")
        response = _Response({"message": {"content": "small"}, "padding": "x" * 2_100_000})
        with patch("my_last_ai_girlfriends.providers._open_without_redirects", return_value=response):
            with self.assertRaisesRegex(ProviderError, "response exceeded"):
                provider.complete([{"role": "user", "content": "hello"}], 128, 3)
        self.assertFalse(provider.status()["connected"])

    def test_gemini_request_uses_bearer_and_real_response(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["authorization"] = request.headers["Authorization"]
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response({"id": "req-1", "model": "gemini-3.8-flash", "choices": [{"message": {"content": "real answer"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})

        with patch("my_last_ai_girlfriends.providers._open_without_redirects", fake_urlopen):
            result = provider.complete([{"role": "user", "content": "hello"}], 128, 7)
        self.assertEqual(captured["url"], "https://example.test/v1beta/openai/chat/completions")
        self.assertEqual(captured["authorization"], "Bearer secret-key")
        self.assertEqual(captured["body"]["model"], "gemini-3.8-flash")
        self.assertEqual(captured["timeout"], 7)
        self.assertTrue(result.ai_generated)
        self.assertTrue(provider.status()["connected"])

    def test_gemini_malformed_response_fails_without_demo_fallback(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        with patch("my_last_ai_girlfriends.providers._open_without_redirects", lambda *_args, **_kwargs: _Response({"choices": []})):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([{"role": "user", "content": "hello"}], 128, 7)
        self.assertEqual(caught.exception.code, "PROVIDER_SCHEMA")

    def test_gemini_rejects_empty_and_unsupported_tool_outputs(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        for payload, code in (
            ({"choices": [{"message": {"content": ""}}]}, "PROVIDER_EMPTY_OUTPUT"),
            ({"choices": [{"message": {"content": "answer", "tool_calls": [{"id": "x"}]}}]}, "PROVIDER_TOOL_CALL_REJECTED"),
        ):
            with self.subTest(code=code), patch("my_last_ai_girlfriends.providers._open_without_redirects", lambda *_args, **_kwargs: _Response(payload)):
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([{"role": "user", "content": "hello"}], 128, 7)
                self.assertEqual(caught.exception.code, code)

    def test_gemini_rejects_oversized_output_and_resets_connection_status(self):
        provider = GeminiProvider("https://example.test/v1beta/openai/", "secret-key", "gemini-3.8-flash", 0.75, 3.75)
        payload = {"choices": [{"message": {"content": "x" * 2049}}], "usage": {"prompt_tokens": 1, "completion_tokens": 999}}
        with patch("my_last_ai_girlfriends.providers._open_without_redirects", lambda *_args, **_kwargs: _Response(payload)):
            with self.assertRaisesRegex(ProviderError, "output bound"):
                provider.complete([{"role": "user", "content": "hello"}], 256, 7)
        self.assertFalse(provider.status()["connected"])
        with patch("my_last_ai_girlfriends.providers._open_without_redirects", side_effect=urllib.error.URLError("offline")):
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

            with self.subTest(status=status), patch("my_last_ai_girlfriends.providers._open_without_redirects", raise_http_error):
                with self.assertRaises(ProviderError) as caught:
                    provider.complete([{"role": "user", "content": "hello"}], 128, 7)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(caught.exception.usage_unknown, unknown)

        with patch("my_last_ai_girlfriends.providers._open_without_redirects", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(ProviderError) as caught:
                provider.complete([{"role": "user", "content": "hello"}], 128, 7)
        self.assertEqual(caught.exception.code, "PROVIDER_TIMEOUT_OR_NETWORK")
        self.assertTrue(caught.exception.usage_unknown)


if __name__ == "__main__":
    unittest.main()
