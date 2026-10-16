"""Header-based local authentication without query-string tokens."""

from __future__ import annotations

import hashlib
import hmac


class AuthManager:
    def __init__(self, token_hash: str):
        self._token_hash = token_hash

    def verify_bearer(self, header: str | None) -> bool:
        if not header or not header.startswith("Bearer "):
            return False
        token = header[7:].strip()
        if not token or len(token) > 512:
            return False
        candidate = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return hmac.compare_digest(candidate, self._token_hash)
