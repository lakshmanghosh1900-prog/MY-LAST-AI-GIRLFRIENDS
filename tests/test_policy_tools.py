from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.policy import Decision, PolicyEngine
from my_last_ai_girlfriends.tools import SafeFileTool, SafeWebFetcher, ToolError, extract_readable_text


class PolicyAndToolTests(unittest.TestCase):
    def test_policy_rejects_secrets_and_unknown_tools(self):
        policy = PolicyEngine(1000, allow_remote_personal_data=False)
        secret = policy.check_message("Here is my password: secret-value", "fake")
        self.assertEqual(secret.decision, Decision.DENY)
        unknown = policy.check_tool("shell.exec", {"command": "whoami"})
        self.assertEqual(unknown.code, "TOOL_NOT_ALLOWLISTED")

    def test_remote_personal_data_is_safe_stopped(self):
        policy = PolicyEngine(1000, allow_remote_personal_data=False)
        result = policy.check_message("remember my private journal", "gemini")
        self.assertEqual(result.decision, Decision.SAFE_STOP)

    def test_file_tool_blocks_escape_binary_and_oversize(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "notes.txt").write_text("safe notes", encoding="utf-8")
            (root / "binary.txt").write_bytes(b"bad\x00data")
            (root / "large.txt").write_text("x" * 20, encoding="utf-8")
            tool = SafeFileTool(root, max_bytes=10)
            self.assertEqual(tool.read_text("notes.txt").text, "safe notes")
            with self.assertRaisesRegex(ToolError, "outside"):
                tool.read_text("../notes.txt")
            with self.assertRaises(ToolError):
                tool.read_text("binary.txt")
            with self.assertRaises(ToolError):
                tool.read_text("large.txt")
            with self.assertRaises(ToolError):
                tool.read_text("missing.txt")

    def test_file_tool_rejects_symlink_when_supported(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "target.txt"
            target.write_text("safe", encoding="utf-8")
            link = root / "link.txt"
            try:
                link.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation is unavailable on this Windows account")
            with self.assertRaises(ToolError):
                SafeFileTool(root, 100).read_text("link.txt")

    def test_fetcher_rejects_unsafe_url_forms(self):
        fetcher = SafeWebFetcher(1024, 1)
        for url in (
            "http://example.com",
            "https://user:password@example.com",
            "https://example.com:8443",
            "file:///etc/passwd",
            "https://localhost/",
            "https://example.com/#fragment",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ToolError):
                    fetcher._parse_url(url)

    def test_fetcher_rejects_private_resolved_address(self):
        fetcher = SafeWebFetcher(1024, 1)
        with patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaisesRegex(ToolError, "public"):
                fetcher._resolve_public("example.com")

    def test_html_extraction_removes_scripts_styles_and_normalizes_text(self):
        markup = "<html><head><style>.secret{display:none}</style><script>steal()</script></head><body><h1>Hello &amp; welcome</h1><p>Readable <b>text</b>.</p><ul><li>One</li><li>Two</li></ul><noscript>hidden</noscript></body></html>"
        text = extract_readable_text(markup)
        self.assertIn("Hello & welcome", text)
        self.assertIn("Readable text", text)
        self.assertIn("One", text)
        self.assertNotIn("steal", text)
        self.assertNotIn("secret", text)
        self.assertNotIn("hidden", text)


if __name__ == "__main__":
    unittest.main()
