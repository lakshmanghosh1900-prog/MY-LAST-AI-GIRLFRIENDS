from __future__ import annotations

import unittest

from my_last_ai_girlfriends.orchestration import OrchestrationError, run_bounded_local_pipeline


class OrchestrationTests(unittest.TestCase):
    def test_limits_reject_booleans_floats_and_strings(self):
        invalid_cases = (
            {"max_depth": True},
            {"max_depth": 1.5},
            {"max_depth": "1"},
            {"max_roles": False},
            {"max_roles": 2.5},
            {"max_roles": "2"},
        )
        for overrides in invalid_cases:
            with self.subTest(overrides=overrides), self.assertRaises(OrchestrationError) as caught:
                run_bounded_local_pipeline("run-1", "plan", **overrides)
            self.assertEqual(caught.exception.code, "AGENT_LIMIT_INVALID")

    def test_integer_limits_remain_bounded_and_valid(self):
        result = run_bounded_local_pipeline("run-2", "plan", max_depth=3, max_roles=2)
        self.assertEqual(result.depth, 3)
        self.assertEqual(result.roles, ("planner", "researcher"))
        for overrides in ({"max_depth": -1}, {"max_depth": 4}, {"max_roles": 0}, {"max_roles": 6}):
            with self.subTest(overrides=overrides), self.assertRaises(OrchestrationError):
                run_bounded_local_pipeline("run-3", "plan", **overrides)


if __name__ == "__main__":
    unittest.main()
