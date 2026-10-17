from __future__ import annotations

import unittest

from my_last_ai_girlfriends.policy import Decision, PolicyEngine
from my_last_ai_girlfriends.tool_registry import ToolRegistryError, get_tool, list_tools


class ToolRegistryTests(unittest.TestCase):
    def test_registry_is_static_read_only_and_schema_validated(self):
        names = {item["name"] for item in list_tools()}
        self.assertEqual(names, {"file.read_text", "web.fetch"})
        self.assertTrue(all(item["read_only"] for item in list_tools()))
        with self.assertRaisesRegex(ToolRegistryError, "Unknown"):
            get_tool("file.read_text").validate({"path": "notes.txt", "extra": True})
        policy = PolicyEngine(1000, False)
        self.assertEqual(policy.check_tool("shell.exec", {"command": "id"}).decision, Decision.DENY)


if __name__ == "__main__":
    unittest.main()
