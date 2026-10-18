from __future__ import annotations

import unittest

from my_last_ai_girlfriends.redaction import redact


class RedactionTests(unittest.TestCase):
    def test_sensitive_query_parameters_are_redacted_without_hiding_safe_params(self):
        request = (
            "GET /research?conversation_id=local-123&access_token=access-secret"
            "&client_secret=client-secret&X-Amz-Signature=signed-secret HTTP/1.1"
        )
        result = redact(request)

        self.assertIn("conversation_id=local-123", result)
        for secret in ("access-secret", "client-secret", "signed-secret"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, result)
        self.assertIn("access_token=[REDACTED]", result)
        self.assertIn("client_secret=[REDACTED]", result)
        self.assertIn("X-Amz-Signature=[REDACTED]", result)

    def test_query_redaction_handles_empty_values_and_fragments(self):
        value = "GET /x?token=&next=visible#secret-fragment HTTP/1.1"
        result = redact(value)
        self.assertIn("token=[REDACTED]", result)
        self.assertIn("next=visible", result)


if __name__ == "__main__":
    unittest.main()
