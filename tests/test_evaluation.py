from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from my_last_ai_girlfriends.evaluation import EVALUATION_VERSION, run_local_evaluation
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService

from test_budget_service import make_config


class EvaluationTests(unittest.TestCase):
    def test_local_evaluation_is_versioned_and_truthful(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            report = run_local_evaluation(service)
            self.assertEqual(report.version, EVALUATION_VERSION)
            self.assertTrue(report.passed)
            self.assertEqual(len(report.cases), 3)
            service.close()


if __name__ == "__main__":
    unittest.main()
