from __future__ import annotations

import unittest

from my_last_ai_girlfriends.documents import answer_from_document_chunks


class DocumentAnswerContractTests(unittest.TestCase):
    def test_supported_answer_is_bounded_and_carries_stable_citation_fields(self):
        result = answer_from_document_chunks(
            "local guide",
            [
                {
                    "document_id": "doc-1",
                    "path": "guide.md",
                    "ordinal": 0,
                    "content_sha256": "a" * 64,
                    "content": "This local guide explains the safe setup.",
                }
            ],
            max_chars=120,
        )

        self.assertEqual(result["evidence_status"], "SUPPORTED_EVIDENCE")
        self.assertFalse(result["ai_generated"])
        self.assertLessEqual(len(result["answer"]), 120)
        self.assertEqual(
            set(result["citations"][0]),
            {"document_id", "path", "ordinal", "content_sha256", "excerpt", "matched_terms"},
        )

    def test_missing_evidence_is_explicit_and_has_no_citations(self):
        result = answer_from_document_chunks(
            "unrelated question",
            [
                {
                    "document_id": "doc-1",
                    "path": "guide.md",
                    "ordinal": 0,
                    "content_sha256": "b" * 64,
                    "content": "A local guide about safe setup.",
                }
            ],
        )

        self.assertEqual(result["evidence_status"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["citations"], [])
        self.assertIn("no answer was generated", result["answer"])
        self.assertTrue(result["local_only"])


if __name__ == "__main__":
    unittest.main()
