"""Bounded public-URL research runs with explicit source provenance."""

from __future__ import annotations

import hashlib
import re
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
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_NEGATION_TOKENS = frozenset({"not", "no", "never", "cannot", "isnt", "doesnt", "without"})
_SENTENCE_RE = re.compile(r"[^.!?;\n]+")


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _WORD_RE.findall(value))


def _claim_stance(claim_tokens: tuple[str, ...], content: str) -> str | None:
    """Classify lexical support without treating an unrelated negation as a conflict."""

    required = set(claim_tokens)
    for sentence in _SENTENCE_RE.findall(content):
        sentence_tokens = _tokens(sentence)
        if not required.issubset(sentence_tokens):
            continue
        positions = [index for index, token in enumerate(sentence_tokens) if token in required]
        window = sentence_tokens[max(0, min(positions) - 1) : max(positions) + 1]
        if any(token in _NEGATION_TOKENS for token in window):
            return "conflicting"
        return "supporting"
    return None


def analyze_claims(claims: list[str], sources: list[dict]) -> dict:
    if not isinstance(claims, list) or not claims or len(claims) > 5:
        raise ResearchError("RESEARCH_CLAIMS_INVALID", "Provide between one and five bounded claims.")
    results = []
    for claim in claims:
        if not isinstance(claim, str) or not claim.strip() or len(claim) > 300:
            raise ResearchError("RESEARCH_CLAIM_INVALID", "Each claim must be a non-empty bounded string.")
        lower = claim.casefold()
        if any(marker in lower for marker in ("password", "api key", "secret", "token")):
            raise ResearchError("RESEARCH_CLAIM_PROHIBITED", "Secret-like claims are not accepted.")
        claim_tokens = tuple(dict.fromkeys(token for token in _tokens(claim) if len(token) > 2))
        supporting = []
        conflicting = []
        for source in sources:
            if not claim_tokens:
                continue
            stance = _claim_stance(claim_tokens, str(source.get("content", "")))
            if stance is None:
                continue
            ordinal = int(source["ordinal"])
            citation = {
                "label": f"S{ordinal + 1}",
                "source_id": source["id"],
                "ordinal": ordinal,
                "requested_url": source.get("requested_url"),
                "url": source["final_url"],
                "excerpt": source["excerpt"],
                "content_sha256": source["content_sha256"],
                "matched_terms": len(claim_tokens),
                "stance": stance,
            }
            (conflicting if stance == "conflicting" else supporting).append(citation)
        if supporting and conflicting:
            classification = "CONFLICTING_EVIDENCE"
        elif supporting:
            classification = "SUPPORTED_EVIDENCE"
        elif conflicting:
            classification = "CONFLICTING_EVIDENCE"
        else:
            classification = "INSUFFICIENT_EVIDENCE"
        results.append({"claim": claim.strip(), "classification": classification, "heuristic": True, "citations": supporting + conflicting})
    return {"results": results, "heuristic": True, "disclaimer": "Heuristic lexical evidence comparison; this is not proof of truth.", "local_only": True, "ai_generated": False}


def validate_research_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise ResearchError("RESEARCH_URL_INVALID", "Each research URL must be a bounded HTTPS URL.")
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise ResearchError("RESEARCH_URL_INVALID", "Research URL syntax is invalid.") from exc
    if parts.scheme != "https" or not parts.netloc or parts.username or parts.password or parts.fragment:
        raise ResearchError("RESEARCH_URL_INVALID", "Research accepts credential-free HTTPS URLs without fragments.")
    try:
        port = parts.port
    except ValueError as exc:
        raise ResearchError("RESEARCH_URL_PORT", "Research accepts only HTTPS port 443.") from exc
    if port not in {None, 443}:
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
