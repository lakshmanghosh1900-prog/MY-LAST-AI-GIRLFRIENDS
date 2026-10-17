"""Bounded local text-document indexing with deterministic provenance."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .tools import FileResult, SafeFileTool, ToolError


class DocumentError(ValueError):
    """A safe document-indexing error suitable for an authenticated API."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class IndexedDocument:
    path: str
    content_sha256: str
    byte_count: int
    suffix: str
    chunks: tuple[str, ...]


_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


def lexical_tokens(value: str) -> tuple[str, ...]:
    return tuple(token.casefold() for token in _WORD_RE.findall(value))


def answer_from_document_chunks(query: str, chunks: list[dict], limit: int = 6, max_chars: int = 2400) -> dict:
    """Build bounded, extractive local evidence without invoking a provider."""

    query_tokens = lexical_tokens(query)
    if not query_tokens:
        raise DocumentError("DOCUMENT_QUERY_REQUIRED", "A search query is required.")
    normalized_query = " ".join(query_tokens)
    ranked: list[tuple[int, int, dict]] = []
    for item in chunks:
        content = str(item.get("content", ""))
        content_tokens = set(lexical_tokens(content))
        coverage = len(set(query_tokens) & content_tokens)
        phrase = int(normalized_query in " ".join(lexical_tokens(content)))
        if coverage:
            ranked.append((coverage, phrase, item))
    ranked.sort(key=lambda value: (-value[0], -value[1], value[2]["path"], value[2]["ordinal"], value[2]["document_id"]))
    selected = ranked[:limit]
    citations = []
    lines = ["Local evidence (not AI):"]
    remaining = max_chars - len(lines[0])
    for coverage, _phrase, item in selected:
        excerpt = " ".join(str(item["content"]).split())[:360]
        line = f"- {item['path']} [chunk {item['ordinal']}] — {excerpt}"
        if len(line) > remaining:
            line = line[: max(0, remaining)].rstrip()
        if not line:
            break
        lines.append(line)
        remaining -= len(line) + 1
        citations.append({
            "document_id": item["document_id"],
            "path": item["path"],
            "ordinal": item["ordinal"],
            "content_sha256": item["content_sha256"],
            "excerpt": excerpt,
            "matched_terms": coverage,
        })
        if remaining <= 0:
            break
    if not selected:
        lines.append("No matching indexed evidence was found.")
    return {"answer": "\n".join(lines)[:max_chars], "citations": citations, "local_only": True, "ai_generated": False}


def chunk_text(text: str, max_chars: int = 2000) -> tuple[str, ...]:
    if max_chars < 128:
        raise DocumentError("DOCUMENT_CHUNK_LIMIT_INVALID", "Document chunk limit is too small.")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise DocumentError("DOCUMENT_EMPTY", "The document has no readable text.")
    chunks: list[str] = []
    start = 0
    while start < len(normalized):
        end = min(len(normalized), start + max_chars)
        if end < len(normalized):
            boundary = normalized.rfind("\n", start, end)
            if boundary > start + max_chars // 2:
                end = boundary
        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return tuple(chunks)


def read_and_prepare(file_tool: SafeFileTool, relative_path: str, max_chunk_chars: int = 2000) -> IndexedDocument:
    try:
        result: FileResult = file_tool.read_text(relative_path)
    except ToolError as exc:
        raise DocumentError(exc.code, str(exc)) from exc
    chunks = chunk_text(result.text, max_chunk_chars)
    return IndexedDocument(
        path=result.relative_path,
        content_sha256=hashlib.sha256(result.text.encode("utf-8")).hexdigest(),
        byte_count=result.byte_count,
        suffix=result.relative_path.rsplit(".", 1)[-1].lower() if "." in result.relative_path else "",
        chunks=chunks,
    )
