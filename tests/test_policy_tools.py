from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from my_last_ai_girlfriends.policy import Decision, PolicyEngine
from my_last_ai_girlfriends.tools import SafeFileTool, SafeWebFetcher, ToolError, extract_readable_text


class FakeFetchResponse:
    def __init__(self, status=200, headers=None, body=b""):
        self.status = status
        self.headers = headers or {}
        self.body = body
        self.read_limits = []
        self.closed = False

    def getheader(self, name):
        return next((value for key, value in self.headers.items() if key.lower() == name.lower()), None)

    def read(self, limit=-1):
        self.read_limits.append(limit)
        return self.body if limit < 0 else self.body[:limit]

    def close(self):
        self.closed = True


class FakePinnedConnection:
    def __init__(self, response):
        self.response = response
        self.request_data = None
        self.closed = False

    def request(self, method, target, headers):
        self.request_data = (method, target, headers)

    def getresponse(self):
        return self.response

    def close(self):
        self.closed = True


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
        with self.assertRaises(ToolError):
            fetcher._parse_url("https://example.com:bad")
        with self.assertRaisesRegex(ToolError, "syntax"):
            fetcher._parse_url("https://[::1")

    def test_fetcher_rejects_private_resolved_address(self):
        fetcher = SafeWebFetcher(1024, 1)
        with patch.object(socket, "getaddrinfo", return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaisesRegex(ToolError, "public"):
                fetcher._resolve_public("example.com")

    def test_fetcher_pins_public_resolution_and_extracts_bounded_html(self):
        response = FakeFetchResponse(
            headers={"Content-Type": "text/html; charset=utf-8"},
            body=b"<html><script>private</script><p>Hello &amp; welcome</p></html>",
        )
        connection = FakePinnedConnection(response)
        fetcher = SafeWebFetcher(max_bytes=512, timeout_seconds=1)
        with patch.object(fetcher, "_resolve_public", return_value="93.184.216.34") as resolver, patch(
            "my_last_ai_girlfriends.tools._PinnedHTTPSConnection", return_value=connection
        ) as connection_factory:
            result = fetcher.fetch("https://example.com/article?topic=local")

        self.assertEqual(result.url, "https://example.com/article?topic=local")
        self.assertEqual(result.content_type, "text/html")
        self.assertIn("Hello & welcome", result.text)
        self.assertNotIn("private", result.text)
        resolver.assert_called_once_with("example.com")
        self.assertEqual(connection_factory.call_args.args[:4], ("example.com", "93.184.216.34", 443, 1))
        self.assertEqual(connection.request_data[0:2], ("GET", "/article?topic=local"))
        self.assertEqual(connection.request_data[2]["Host"], "example.com")
        self.assertTrue(connection.closed)
        self.assertTrue(response.closed)

    def test_fetcher_revalidates_redirect_destination_before_connecting(self):
        response = FakeFetchResponse(status=302, headers={"Location": "https://127.0.0.1/private"}, body=b"")
        connection = FakePinnedConnection(response)
        fetcher = SafeWebFetcher(max_bytes=512, timeout_seconds=1)

        def resolve(host):
            if host == "example.com":
                return "93.184.216.34"
            raise ToolError("PRIVATE_DESTINATION", "private destination rejected")

        with patch.object(fetcher, "_resolve_public", side_effect=resolve), patch(
            "my_last_ai_girlfriends.tools._PinnedHTTPSConnection", return_value=connection
        ) as connection_factory:
            with self.assertRaisesRegex(ToolError, "private destination"):
                fetcher.fetch("https://example.com/start")

        connection_factory.assert_called_once()
        self.assertTrue(connection.closed)
        self.assertTrue(response.closed)
        self.assertEqual(response.read_limits, [4096])

    def test_fetcher_enforces_redirect_limit_and_response_byte_limit(self):
        redirected = FakeFetchResponse(status=302, headers={"Location": "https://other.example/next"})
        redirect_connection = FakePinnedConnection(redirected)
        fetcher = SafeWebFetcher(max_bytes=512, timeout_seconds=1, max_redirects=0)
        with patch.object(fetcher, "_resolve_public", return_value="93.184.216.34"), patch(
            "my_last_ai_girlfriends.tools._PinnedHTTPSConnection", return_value=redirect_connection
        ):
            with self.assertRaisesRegex(ToolError, "redirect limit"):
                fetcher.fetch("https://example.com/start")
        self.assertTrue(redirect_connection.closed)

        oversized = FakeFetchResponse(headers={"Content-Type": "text/plain"}, body=b"x" * 513)
        oversized_connection = FakePinnedConnection(oversized)
        with patch.object(fetcher, "_resolve_public", return_value="93.184.216.34"), patch(
            "my_last_ai_girlfriends.tools._PinnedHTTPSConnection", return_value=oversized_connection
        ):
            with self.assertRaisesRegex(ToolError, "configured limit"):
                fetcher.fetch("https://example.com/large")
        self.assertEqual(oversized.read_limits, [513])
        self.assertTrue(oversized_connection.closed)

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
