"""Bounded local text-document indexing with deterministic provenance."""

from __future__ import annotations

import hashlib
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
