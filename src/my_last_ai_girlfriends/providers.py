"""Truthful offline demo and configurable Gemini OpenAI-compatible provider."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable
from urllib.parse import urlsplit, urlunsplit


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent provider POST bodies from being forwarded to redirect targets."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_without_redirects(request: urllib.request.Request, timeout: int):
    opener = urllib.request.build_opener(_NoRedirectHandler())
    return opener.open(request, timeout=timeout)


class ProviderError(RuntimeError):
    def __init__(self, code: str, message: str, usage_unknown: bool = False):
        super().__init__(message)
        self.code = code
        self.usage_unknown = usage_unknown


@dataclass(frozen=True)
class ProviderResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    request_id: str | None
    duration_ms: int
    ai_generated: bool


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


class Provider:
    name = "provider"
    model = "unknown"
    ai_generated = False

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        raise NotImplementedError

    def complete(self, messages: Iterable[dict[str, str]], max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        raise NotImplementedError

    def status(self) -> dict:
        return {"provider": self.name, "model": self.model, "connected": False, "ai_generated": self.ai_generated}


class OfflineDemoProvider(Provider):
    """Deterministic local preview. It never claims to be a language model."""

    name = "offline-demo"
    ai_generated = False

    def __init__(self, model: str = "offline-demo"):
        self.model = model

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        del input_tokens, output_tokens
        return 0

    def complete(self, messages: Iterable[dict[str, str]], max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        del timeout_seconds
        started = time.monotonic()
        items = list(messages)
        user_content = next((m["content"] for m in reversed(items) if m["role"] == "user"), "")
        if "<untrusted_file_data>" in user_content or "<untrusted_web_data>" in user_content:
            label = "local file" if "<untrusted_file_data>" in user_content else "public web page"
            tag = "untrusted_file_data" if label == "local file" else "untrusted_web_data"
            body = user_content.split(f"<{tag}>", 1)[1].split(f"</{tag}>", 1)[0]
            preview = " ".join(body.strip().split())[:700]
            text = f"Offline demo preview (not AI) — {label}:\n{preview}"
        else:
            text = f"Offline demo (not AI). Your message was received locally:\n{user_content.strip()[:700]}"
        text = text[: max(64, max_output_tokens * 4)]
        return ProviderResult(text, self.name, self.model, sum(estimate_tokens(m["content"]) for m in items), estimate_tokens(text), None, int((time.monotonic() - started) * 1000), False)


def build_chat_completions_url(base_url: str) -> str:
    """Normalize a base URL and append `/chat/completions` exactly once."""

    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("provider base URL must be an absolute HTTP(S) URL")
    path = parsed.path.rstrip("/")
    suffix = "/chat/completions"
    if path.endswith(suffix):
        path = path[: -len(suffix)]
    return urlunsplit((parsed.scheme, parsed.netloc, path + suffix, "", ""))


def build_ollama_chat_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("ollama base URL must be an absolute HTTP(S) URL")
    path = parsed.path.rstrip("/")
    if not path.endswith("/api/chat"):
        path += "/api/chat"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class OllamaProvider(Provider):
    """Optional local Ollama adapter; no remote credential or fake fallback."""

    name = "ollama"
    ai_generated = True

    def __init__(self, base_url: str, model: str):
        self.endpoint = build_ollama_chat_url(base_url)
        self.model = model
        self._connected = False

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        del input_tokens, output_tokens
        return 0

    def status(self) -> dict:
        return {"provider": self.name, "model": self.model, "endpoint": self.endpoint, "connected": self._connected, "ai_generated": True, "local": True}

    def complete(self, messages: Iterable[dict[str, str]], max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        items = list(messages)
        self._connected = False
        body = json.dumps({"model": self.model, "messages": items, "stream": False, "options": {"num_predict": max_output_tokens}}).encode("utf-8")
        request = urllib.request.Request(self.endpoint, data=body, method="POST", headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "my-last-ai-girlfriends/0.2.0"})
        started = time.monotonic()
        try:
            with _open_without_redirects(request, timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise ProviderError(
                        "LOCAL_PROVIDER_HTTP_ERROR",
                        "The local provider returned a non-success HTTP status.",
                        usage_unknown=True,
                    )
                raw = response.read(2_000_000)
                if len(raw) >= 2_000_000:
                    raise ProviderError(
                        "PROVIDER_RESPONSE_TOO_LARGE",
                        "The local provider response exceeded the configured limit.",
                        usage_unknown=True,
                    )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise ProviderError("LOCAL_PROVIDER_UNAVAILABLE", "The local Ollama provider did not return a completed response.", usage_unknown=True) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
            text = payload["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ProviderError("PROVIDER_EMPTY_OUTPUT", "The local provider returned no text.")
            if len(text) > max_output_tokens * 8:
                raise ProviderError("PROVIDER_OUTPUT_TOO_LARGE", "The local provider returned more text than the configured output bound.")
            input_tokens = int(payload.get("prompt_eval_count", estimate_tokens(" ".join(m["content"] for m in items))))
            output_tokens = int(payload.get("eval_count", estimate_tokens(text)))
        except ProviderError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("PROVIDER_SCHEMA", "The local provider response did not match the expected schema.", usage_unknown=True) from exc
        self._connected = True
        return ProviderResult(text, self.name, self.model, input_tokens, output_tokens, None, int((time.monotonic() - started) * 1000), True)


class GeminiProvider(Provider):
    """Gemini through Google's documented OpenAI-compatible endpoint."""

    name = "gemini"
    ai_generated = True

    def __init__(self, base_url: str, api_key: str, model: str, input_price: Decimal, output_price: Decimal):
        self.endpoint = build_chat_completions_url(base_url)
        self.api_key = api_key
        self.model = model
        self.input_price = input_price
        self.output_price = output_price
        self._connected = False

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        value = (Decimal(input_tokens) * self.input_price + Decimal(output_tokens) * self.output_price) / Decimal(1_000_000)
        return int((value * Decimal(1_000_000)).to_integral_value())

    def status(self) -> dict:
        return {"provider": self.name, "model": self.model, "endpoint": self.endpoint, "connected": self._connected, "ai_generated": True}

    def complete(self, messages: Iterable[dict[str, str]], max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        items = list(messages)
        self._connected = False
        body = json.dumps({"model": self.model, "messages": items, "max_tokens": max_output_tokens, "stream": False}).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "my-last-ai-girlfriends/0.2.0",
            },
        )
        started = time.monotonic()
        try:
            with _open_without_redirects(request, timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise ProviderError("PROVIDER_HTTP_ERROR", "The provider returned a non-success HTTP status.", usage_unknown=True)
                raw = response.read(2_000_000)
                if len(raw) >= 2_000_000:
                    raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE", "The provider response exceeded the configured limit.", usage_unknown=True)
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ProviderError("PROVIDER_AUTHENTICATION", "Gemini authentication was rejected.") from exc
            if exc.code == 429:
                raise ProviderError("PROVIDER_RATE_LIMIT", "Gemini rate limit or quota was reached.", usage_unknown=True) from exc
            raise ProviderError("PROVIDER_HTTP_ERROR", "Gemini returned an HTTP error.", usage_unknown=True) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise ProviderError("PROVIDER_TIMEOUT_OR_NETWORK", "Gemini did not return a completed response.", usage_unknown=True) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
            message = payload["choices"][0]["message"]
            if message.get("tool_calls") or message.get("function_call"):
                raise ProviderError("PROVIDER_TOOL_CALL_REJECTED", "Gemini returned an unsupported tool call.")
            text = message["content"]
            if not isinstance(text, str) or not text.strip():
                raise ProviderError("PROVIDER_EMPTY_OUTPUT", "Gemini returned no text.")
            usage = payload.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", estimate_tokens(" ".join(m["content"] for m in items))))
            output_tokens = int(usage.get("completion_tokens", estimate_tokens(text)))
            if input_tokens < 0 or output_tokens < 0:
                raise ValueError("negative token usage")
            if len(text) > max_output_tokens * 8:
                raise ProviderError("PROVIDER_OUTPUT_TOO_LARGE", "Gemini returned more text than the configured output bound.")
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("PROVIDER_SCHEMA", "Gemini response did not match the expected schema.", usage_unknown=True) from exc
        self._connected = True
        return ProviderResult(text, self.name, str(payload.get("model", self.model)), input_tokens, output_tokens, str(payload.get("id")) if payload.get("id") else None, int((time.monotonic() - started) * 1000), True)
