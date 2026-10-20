from __future__ import annotations

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock

from my_last_ai_girlfriends.policy import Decision, PolicyEngine
from my_last_ai_girlfriends.tool_registry import ToolRegistryError, execute_registered_tool, get_tool, list_tools
from my_last_ai_girlfriends.tools import SafeFileTool


class ToolRegistryTests(unittest.TestCase):
    def test_registry_is_static_read_only_and_schema_validated(self):
        names = {item["name"] for item in list_tools()}
        self.assertEqual(names, {"file.read_text", "web.fetch"})
        self.assertTrue(all(item["read_only"] for item in list_tools()))
        with self.assertRaisesRegex(ToolRegistryError, "Unknown"):
            get_tool("file.read_text").validate({"path": "notes.txt", "extra": True})
        policy = PolicyEngine(1000, False)
        self.assertEqual(policy.check_tool("shell.exec", {"command": "id"}).decision, Decision.DENY)

    def test_tool_lookup_rejects_invalid_name_types_and_lengths(self):
        for name in (None, [], {}, "", "x" * 129):
            with self.subTest(name_type=type(name).__name__):
                with self.assertRaisesRegex(ToolRegistryError, "valid registered tool name"):
                    get_tool(name)

    def test_registered_handlers_are_the_only_execution_path(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "notes.txt").write_text("local tool evidence", encoding="utf-8")
            result = execute_registered_tool("file.read_text", {"path": "notes.txt"}, file_tool=SafeFileTool(root, 1024), web_tool=Mock())
            self.assertEqual(result["text"], "local tool evidence")
            with self.assertRaises(ToolRegistryError):
                execute_registered_tool("shell.exec", {"command": "id"}, file_tool=SafeFileTool(root, 1024), web_tool=Mock())


if __name__ == "__main__":
    unittest.main()
