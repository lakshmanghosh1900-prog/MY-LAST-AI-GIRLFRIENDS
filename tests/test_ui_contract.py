from __future__ import annotations

import unittest
from pathlib import Path


class UiContractTests(unittest.TestCase):
    def test_ui_is_branded_responsive_and_text_safe(self):
        html = (Path(__file__).parents[1] / "src" / "my_last_ai_girlfriends" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("MY LAST AI GIRLFRIENDS", html)
        self.assertIn("My Companion", html)
        self.assertIn("@media (max-width:760px)", html)
        self.assertIn("Offline demo", html)
        self.assertNotIn("innerHTML", html)
        self.assertIn("mlag-token", html)
        self.assertIn("Shift+Enter", html)
        self.assertIn("Local memory", html)
        self.assertIn("/v1/memory", html)


if __name__ == "__main__":
    unittest.main()
