"""Read-only tools with path and network boundary checks."""

from __future__ import annotations

import http.client
import html
import ipaddress
import io
import re
import socket
import ssl
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree
from urllib.parse import SplitResult, urlsplit, urlunsplit


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FileResult:
    relative_path: str
    text: str
    byte_count: int


class SafeFileTool:
    text_suffixes = frozenset({".txt", ".md", ".markdown", ".json", ".csv", ".log", ".py", ".toml", ".yaml", ".yml"})
    document_suffixes = frozenset({".docx", ".pdf"})
    allowed_suffixes = text_suffixes | document_suffixes

    def __init__(self, root: Path, max_bytes: int):
        self.root = root.resolve()
        self.max_bytes = max_bytes

    def _safe_path(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path.strip():
            raise ToolError("FILE_PATH_REQUIRED", "A relative file path is required.")
        if "\x00" in relative_path:
            raise ToolError("FILE_PATH_INVALID", "The path contains a NUL byte.")
        normalized = relative_path.replace("\\", "/")
        candidate = Path(normalized)
        if ".." in candidate.parts:
            raise ToolError("FILE_PATH_ESCAPE", "The path resolves outside the approved folder.")
        if candidate.is_absolute() or candidate.drive or any(part in {"", "."} for part in candidate.parts):
            raise ToolError("FILE_PATH_INVALID", "Only a clean relative path is allowed.")
        if any(part.startswith(".") for part in candidate.parts):
            raise ToolError("FILE_PATH_HIDDEN", "Hidden files are not in the read-only allowlist.")
        try:
            path = (self.root / candidate).resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise ToolError("FILE_NOT_FOUND", "The requested file does not exist.") from exc
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise ToolError("FILE_PATH_ESCAPE", "The path resolves outside the approved folder.") from exc
        current = self.root
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                raise ToolError("FILE_LINK_REJECTED", "Symbolic links are not allowed in the file tool.")
        if not path.is_file() or path.suffix.lower() not in self.allowed_suffixes:
            raise ToolError("FILE_TYPE_REJECTED", "Only approved small text, DOCX or PDF files are allowed.")
        if path.stat().st_size > self.max_bytes:
            raise ToolError("FILE_TOO_LARGE", "The file exceeds the configured limit.")
        return path

    def read_text(self, relative_path: str) -> FileResult:
        path = self._safe_path(relative_path)
        if path.suffix.lower() not in self.text_suffixes:
            raise ToolError("FILE_TYPE_REJECTED", "Use document extraction for DOCX or PDF files.")
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise ToolError("FILE_BINARY_REJECTED", "Binary content is not accepted.")
        return FileResult(relative_path=relative_path.replace("\\", "/"), text=raw.decode("utf-8", errors="replace"), byte_count=len(raw))

    def read_document(self, relative_path: str) -> FileResult:
        path = self._safe_path(relative_path)
        suffix = path.suffix.lower()
        raw = path.read_bytes()
        if suffix in self.text_suffixes:
            if b"\x00" in raw:
                raise ToolError("FILE_BINARY_REJECTED", "Binary content is not accepted.")
            text = raw.decode("utf-8", errors="replace")
        elif suffix == ".docx":
            text = _extract_docx_text(raw, self.max_bytes)
        elif suffix == ".pdf":
            text = _extract_pdf_text(raw, self.max_bytes)
        else:
            raise ToolError("FILE_TYPE_REJECTED", "Only approved text, DOCX or PDF files are supported.")
        if not text.strip():
            raise ToolError("FILE_EMPTY", "The document has no extractable text.")
        return FileResult(relative_path=relative_path.replace("\\", "/"), text=text, byte_count=len(raw))


def _extract_docx_text(raw: bytes, max_bytes: int) -> str:
    """Extract bounded WordprocessingML text without executing document parts."""

    if len(raw) > max_bytes:
        raise ToolError("FILE_TOO_LARGE", "The DOCX file exceeds the configured limit.")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = archive.infolist()
            if len(members) > 256 or any(member.is_dir() for member in members):
                raise ToolError("DOCX_ARCHIVE_REJECTED", "The DOCX archive structure is not supported.")
            total_uncompressed = sum(member.file_size for member in members)
            if total_uncompressed > max_bytes * 4:
                raise ToolError("DOCX_ARCHIVE_TOO_LARGE", "The expanded DOCX content exceeds the limit.")
            names = {member.filename.replace("\\", "/") for member in members}
            if "word/document.xml" not in names:
                raise ToolError("DOCX_DOCUMENT_MISSING", "The DOCX main document is missing.")
            xml = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError) as exc:
        raise ToolError("DOCX_INVALID", "The DOCX container could not be read safely.") from exc
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ToolError("DOCX_XML_INVALID", "The DOCX document XML is invalid.") from exc
    parts: list[str] = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] == "t" and element.text:
            parts.append(element.text)
        elif element.tag.rsplit("}", 1)[-1] in {"p", "br", "tab"}:
            parts.append("\n" if element.tag.rsplit("}", 1)[-1] in {"p", "br"} else "\t")
    return "\n".join(" ".join(line.split()) for line in "".join(parts).splitlines() if line.strip()).strip()


def _decode_pdf_literal(value: bytes) -> str:
    result = bytearray()
    index = 0
    escapes = {ord("n"): 10, ord("r"): 13, ord("t"): 9, ord("b"): 8, ord("f"): 12}
    while index < len(value):
        if value[index] != 92:
            result.append(value[index]); index += 1; continue
        index += 1
        if index >= len(value):
            break
        char = value[index]
        if char in escapes:
            result.append(escapes[char]); index += 1; continue
        if 48 <= char <= 55:
            digits = bytes([char]); index += 1
            while index < len(value) and len(digits) < 3 and 48 <= value[index] <= 55:
                digits += bytes([value[index]]); index += 1
            result.append(int(digits, 8)); continue
        result.append(char); index += 1
    return result.decode("utf-8", errors="replace")


def _extract_pdf_text(raw: bytes, max_bytes: int) -> str:
    """Extract simple PDF text operators without executing embedded content.

    This deliberately supports a bounded text subset, not full PDF rendering.
    Unsupported encodings return a truthful no-text error rather than guessing.
    """

    if len(raw) > max_bytes or not raw.startswith(b"%PDF-"):
        raise ToolError("PDF_INVALID", "The PDF header or size is invalid.")
    text_parts: list[str] = []
    for block in re.findall(rb"BT(.*?)ET", raw, flags=re.DOTALL):
        for match in re.finditer(rb"\((?:\\.|[^\\)])*\)\s*Tj", block):
            literal = match.group(0).rsplit(b")", 1)[0][1:]
            text_parts.append(_decode_pdf_literal(literal))
        for match in re.finditer(rb"<([0-9A-Fa-f\s]+)>\s*Tj", block):
            try:
                text_parts.append(bytes.fromhex(match.group(1).decode()).decode("utf-8", errors="replace"))
            except ValueError:
                continue
    text = " ".join(" ".join(text_parts).split())
    if not text:
        raise ToolError("PDF_TEXT_UNSUPPORTED", "This PDF does not contain extractable text in the supported subset.")
    return text


class _ReadableHTMLParser(HTMLParser):
    """Extract readable page text without executing or returning raw markup."""

    ignored_tags = frozenset({"script", "style", "noscript", "template", "svg", "canvas"})
    block_tags = frozenset({"address", "article", "blockquote", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "main", "p", "pre", "section", "table", "tr", "ul", "ol"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self.ignored_tags:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag in self.block_tags:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag in self.block_tags:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        value = html.unescape("".join(self.parts))
        lines = [" ".join(line.split()) for line in value.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def extract_readable_text(markup: str) -> str:
    parser = _ReadableHTMLParser()
    parser.feed(markup)
    parser.close()
    return parser.text()


def _public_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as exc:
        raise ToolError("DNS_ADDRESS_INVALID", "The resolved address is invalid.") from exc
    if not address.is_global:
        raise ToolError("PRIVATE_DESTINATION", "The destination is not a public address.")
    return address


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, resolved_ip: str, port: int, timeout: int, context: ssl.SSLContext):
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._resolved_ip = resolved_ip

    def connect(self) -> None:  # pragma: no cover - exercised through integration smoke tests
        raw = socket.create_connection((self._resolved_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


@dataclass(frozen=True)
class FetchResult:
    url: str
    content_type: str
    text: str
    byte_count: int


class SafeWebFetcher:
    def __init__(self, max_bytes: int, timeout_seconds: int, max_redirects: int = 3):
        self.max_bytes = max_bytes
        self.timeout_seconds = timeout_seconds
        self.max_redirects = max_redirects

    def _parse_url(self, url: str) -> SplitResult:
        if not isinstance(url, str) or len(url) > 2048:
            raise ToolError("URL_INVALID", "The URL is missing or too long.")
        try:
            parts = urlsplit(url)
        except ValueError as exc:
            raise ToolError("URL_INVALID", "The URL syntax is invalid.") from exc
        if parts.scheme != "https" or parts.hostname is None or parts.username or parts.password or parts.fragment:
            raise ToolError("URL_INVALID", "Only credential-free HTTPS URLs without fragments are allowed.")
        try:
            port = parts.port
        except ValueError as exc:
            raise ToolError("URL_INVALID", "The URL port is invalid.") from exc
        if port not in {None, 443}:
            raise ToolError("URL_PORT_REJECTED", "Only HTTPS port 443 is allowed.")
        if parts.query and len(parts.query) > 1024:
            raise ToolError("URL_QUERY_TOO_LARGE", "The URL query is too large.")
        try:
            host = parts.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        except UnicodeError as exc:
            raise ToolError("URL_HOST_INVALID", "The host name is invalid.") from exc
        if not host or any(character.isspace() for character in host) or host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            raise ToolError("PRIVATE_DESTINATION", "The host is not a public web destination.")
        return SplitResult("https", host, parts.path or "/", parts.query, "")

    def _resolve_public(self, host: str) -> str:
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise ToolError("DNS_LOOKUP_FAILED", "The web host could not be resolved.") from exc
        addresses = []
        for info in infos:
            address = info[4][0]
            _public_ip(address)
            addresses.append(address)
        if not addresses:
            raise ToolError("DNS_LOOKUP_FAILED", "The web host has no usable address.")
        return addresses[0]

    def fetch(self, url: str) -> FetchResult:
        current = self._parse_url(url)
        for _ in range(self.max_redirects + 1):
            resolved_ip = self._resolve_public(current.hostname or "")
            context = ssl.create_default_context()
            connection = _PinnedHTTPSConnection(current.hostname or "", resolved_ip, 443, self.timeout_seconds, context)
            try:
                target = urlunsplit(("", "", current.path or "/", current.query, ""))
                connection.request("GET", target, headers={"Host": current.hostname or "", "Accept": "text/plain, text/markdown, text/html, application/json", "Accept-Encoding": "identity", "User-Agent": "my-last-ai-girlfriends/0.2.0"})
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    response.read(4096)
                    if not location:
                        raise ToolError("REDIRECT_INVALID", "The redirect has no destination.")
                    next_url = urlsplit(location)
                    if not next_url.scheme:
                        raise ToolError("REDIRECT_INVALID", "Relative redirects are not allowed.")
                    current = self._parse_url(location)
                    continue
                if response.status < 200 or response.status >= 300:
                    raise ToolError("FETCH_STATUS", "The web host returned a non-success status.")
                content_type = (response.getheader("Content-Type") or "").split(";", 1)[0].strip().lower()
                if content_type and content_type not in {"text/plain", "text/markdown", "text/html", "application/json"}:
                    raise ToolError("FETCH_TYPE_REJECTED", "The response content type is not text.")
                body = response.read(self.max_bytes + 1)
                if len(body) > self.max_bytes:
                    raise ToolError("FETCH_TOO_LARGE", "The response exceeds the configured limit.")
                if b"\x00" in body:
                    raise ToolError("FETCH_BINARY_REJECTED", "Binary web content is not accepted.")
                raw_text = body.decode("utf-8", errors="replace")
                readable = extract_readable_text(raw_text) if content_type == "text/html" else raw_text
                return FetchResult(url=urlunsplit(current), content_type=content_type or "text/plain", text=readable, byte_count=len(body))
            except ToolError:
                raise
            except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
                raise ToolError("FETCH_TRANSPORT", "The public fetch did not complete safely.") from exc
            finally:
                connection.close()
        raise ToolError("REDIRECT_LIMIT", "The redirect limit was exceeded.")
