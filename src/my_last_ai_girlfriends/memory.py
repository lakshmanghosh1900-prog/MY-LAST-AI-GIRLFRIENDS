"""Explicit, local-only long-term memory validation and value objects."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import re


MAX_RECALL_QUERY_TOKENS = 64
MAX_RECALL_MEMORY_TOKENS = 256
MAX_RECALL_RESULTS = 20
MAX_RECALL_SCAN_CHARS = 20_000
_LEXICAL_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


class MemoryError(ValueError):
    """A safe, user-visible memory validation or authorization error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class MemoryItem:
    id: str
    scope: str
    conversation_id: str | None
    content: str
    data_class: str
    source_type: str
    created_at: str
    updated_at: str
    expires_at: str | None
    confirmed: bool

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "scope": self.scope,
            "conversation_id": self.conversation_id,
            "content": self.content,
            "data_class": self.data_class,
            "source_type": self.source_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "confirmed": self.confirmed,
        }


def lexical_tokens(value: str, max_tokens: int = MAX_RECALL_MEMORY_TOKENS) -> tuple[str, ...]:
    """Return a bounded, case-insensitive sequence of Unicode word tokens."""

    if not isinstance(value, str) or max_tokens <= 0:
        return ()
    tokens: list[str] = []
    for match in _LEXICAL_TOKEN.finditer(value[:MAX_RECALL_SCAN_CHARS].casefold()):
        tokens.append(match.group(0))
        if len(tokens) >= max_tokens:
            break
    return tuple(tokens)


def rank_memories(
    query: str,
    memories: list[dict],
    limit: int = MAX_RECALL_RESULTS,
) -> list[dict]:
    """Rank memory records by deterministic lexical term overlap.

    Storage order is retained as the final tie-breaker, so equal scores remain
    deterministic while preserving the existing recency/id ordering.
    """

    if limit <= 0:
        return []
    query_tokens = lexical_tokens(query, MAX_RECALL_QUERY_TOKENS)
    if not query_tokens:
        return []
    query_counts = Counter(query_tokens)
    query_terms = set(query_counts)
    ranked: list[tuple[int, int, int, dict]] = []
    for ordinal, item in enumerate(memories):
        content_tokens = lexical_tokens(item.get("content", ""))
        content_counts = Counter(content_tokens)
        matched_terms = query_terms.intersection(content_counts)
        if not matched_terms:
            continue
        term_frequency = sum(min(query_counts[token], content_counts[token]) for token in matched_terms)
        ranked.append((-len(matched_terms), -term_frequency, ordinal, item))
    ranked.sort(key=lambda entry: entry[:3])
    return [entry[3] for entry in ranked[:limit]]


def validate_scope(scope: str, conversation_id: str | None) -> tuple[str, str | None]:
    if scope not in {"global", "conversation"}:
        raise MemoryError("MEMORY_SCOPE_INVALID", "scope must be global or conversation")
    if scope == "conversation" and not conversation_id:
        raise MemoryError("MEMORY_CONVERSATION_REQUIRED", "conversation-scoped memory requires a conversation")
    if scope == "global" and conversation_id is not None:
        raise MemoryError("MEMORY_SCOPE_CONFLICT", "global memory cannot include a conversation")
    return scope, conversation_id


def validate_expiry(expires_at: str | None) -> str | None:
    if expires_at is None or expires_at == "":
        return None
    if not isinstance(expires_at, str) or len(expires_at) > 64:
        raise MemoryError("MEMORY_EXPIRY_INVALID", "expires_at must be an ISO timestamp")
    value = expires_at.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise MemoryError("MEMORY_EXPIRY_INVALID", "expires_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise MemoryError("MEMORY_EXPIRY_TIMEZONE_REQUIRED", "expires_at must include a timezone")
    if parsed.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise MemoryError("MEMORY_EXPIRY_PAST", "expires_at must be in the future")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
