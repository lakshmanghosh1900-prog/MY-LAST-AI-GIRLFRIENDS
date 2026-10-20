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

    def test_additional_credential_query_names_are_redacted(self):
        request = (
            "GET /research?topic=local&access_key=access-secret"
            "&session_id=session-secret&jwt=jwt-secret&X-Credential=credential-secret HTTP/1.1"
        )
        result = redact(request)
        self.assertIn("topic=local", result)
        for secret in ("access-secret", "session-secret", "jwt-secret", "credential-secret"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, result)
        for key in ("access_key", "session_id", "jwt", "X-Credential"):
            with self.subTest(key=key):
                self.assertRegex(result, rf"(?i){key.replace('-', r'\-')}=\[REDACTED\]")

    def test_query_redaction_handles_empty_values_and_fragments(self):
        value = "GET /x?token=&next=visible#secret-fragment HTTP/1.1"
        result = redact(value)
        self.assertIn("token=[REDACTED]", result)
        self.assertIn("next=visible", result)


if __name__ == "__main__":
    unittest.main()
