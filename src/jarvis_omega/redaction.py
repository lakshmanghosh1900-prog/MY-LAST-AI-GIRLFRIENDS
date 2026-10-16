"""Defence-in-depth redaction for audit metadata and user-visible diagnostics."""

from __future__ import annotations

import re


PATTERNS = (
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(password\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"\b(?:sk|AIza)[A-Za-z0-9_-]{16,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"\b\d{10,19}\b"), "[REDACTED_NUMBER]"),
)


def redact(value: str) -> str:
    result = value
    for pattern, replacement in PATTERNS:
        result = pattern.sub(replacement, result)
    return result[:2000]
