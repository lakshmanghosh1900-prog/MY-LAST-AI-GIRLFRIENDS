"""Bounded public-URL research runs with explicit source provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from .tools import FetchResult, SafeWebFetcher, ToolError


class ResearchError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResearchSource:
    requested_url: str
    final_url: str
    content_type: str
    byte_count: int
    content_sha256: str
    excerpt: str
    text: str


_SECRET_QUERY_KEYS = frozenset({"key", "api_key", "apikey", "token", "access_token", "password", "secret", "signature", "sig", "auth"})


def validate_research_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise ResearchError("RESEARCH_URL_INVALID", "Each research URL must be a bounded HTTPS URL.")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password or parts.fragment:
        raise ResearchError("RESEARCH_URL_INVALID", "Research accepts credential-free HTTPS URLs without fragments.")
    if parts.port not in {None, 443}:
        raise ResearchError("RESEARCH_URL_PORT", "Research accepts only HTTPS port 443.")
    for key, _ in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in _SECRET_QUERY_KEYS or any(marker in key.lower() for marker in ("token", "secret", "password", "api")):
            raise ResearchError("RESEARCH_SECRET_QUERY", "Research URLs cannot contain secret-like query parameters.")
    return url


def fetch_source(fetcher: SafeWebFetcher, url: str) -> ResearchSource:
    validated = validate_research_url(url)
    try:
        result: FetchResult = fetcher.fetch(validated)
    except ToolError as exc:
        raise ResearchError(exc.code, str(exc)) from exc
    text = result.text.strip()
    if not text:
        raise ResearchError("RESEARCH_EMPTY_SOURCE", "The public source returned no readable text.")
    return ResearchSource(
        requested_url=validated,
        final_url=result.url,
        content_type=result.content_type,
        byte_count=result.byte_count,
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        excerpt=" ".join(text.split())[:700],
        text=text,
    )
