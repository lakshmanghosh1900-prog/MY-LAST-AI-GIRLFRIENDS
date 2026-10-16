"""Provider boundary with an offline fake and an opt-in OpenAI-compatible adapter."""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable


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


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


class Provider:
    name = "provider"

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        raise NotImplementedError

    def complete(self, messages: Iterable[dict[str, str]], max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        raise NotImplementedError


class FakeProvider(Provider):
    name = "fake"

    def __init__(self, model: str):
        self.model = model

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        return 0

    def complete(self, messages: Iterable[dict[str, str]], max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        del timeout_seconds
        started = time.monotonic()
        items = list(messages)
        user_content = next((m["content"] for m in reversed(items) if m["role"] == "user"), "")
        if "<untrusted_file_data>" in user_content or "<untrusted_web_data>" in user_content:
            if "<untrusted_file_data>" in user_content:
                label = "local file"
                body = user_content.split("<untrusted_file_data>", 1)[1].split("</untrusted_file_data>", 1)[0]
            else:
                label = "public web page"
                body = user_content.split("<untrusted_web_data>", 1)[1].split("</untrusted_web_data>", 1)[0]
            cleaned = " ".join(body.strip().split())
            text = f"Offline safe summary of the {label}: {cleaned[:700]}"
        else:
            cleaned = " ".join(user_content.strip().split())
            text = f"JARVIS OMEGA safe mode received: {cleaned[:700]}"
        text = text[: max(64, max_output_tokens * 4)]
        return ProviderResult(
            text=text,
            provider=self.name,
            model=self.model,
            input_tokens=sum(estimate_tokens(m["content"]) for m in items),
            output_tokens=estimate_tokens(text),
            request_id=None,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


class OpenAICompatibleProvider(Provider):
    name = "openai-compatible"

    def __init__(self, url: str, api_key: str, model: str, input_price: Decimal, output_price: Decimal):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.input_price = input_price
        self.output_price = output_price

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> int:
        value = (Decimal(input_tokens) * self.input_price + Decimal(output_tokens) * self.output_price) / Decimal(1_000_000)
        return int((value * Decimal(1_000_000)).to_integral_value())

    def complete(self, messages: Iterable[dict[str, str]], max_output_tokens: int, timeout_seconds: int) -> ProviderResult:
        items = list(messages)
        body = json.dumps({
            "model": self.model,
            "messages": items,
            "max_tokens": max_output_tokens,
            "stream": False,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "jarvis-omega/0.1.0",
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read(2_000_000)
                if len(raw) >= 2_000_000:
                    raise ProviderError("PROVIDER_RESPONSE_TOO_LARGE", "Provider response exceeded the limit.")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            raise ProviderError("PROVIDER_TRANSPORT", "Provider request was not completed.", usage_unknown=True) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
            choice = payload["choices"][0]
            message = choice["message"]
            if message.get("tool_calls") or message.get("function_call"):
                raise ProviderError("PROVIDER_TOOL_CALL_REJECTED", "Provider returned an unsupported tool call.")
            text = message["content"]
            if not isinstance(text, str) or not text.strip():
                raise ProviderError("PROVIDER_EMPTY_OUTPUT", "Provider returned no text.")
            usage = payload.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", estimate_tokens(" ".join(m["content"] for m in items))))
            output_tokens = int(usage.get("completion_tokens", estimate_tokens(text)))
            if input_tokens < 0 or output_tokens < 0:
                raise ValueError("negative usage")
        except ProviderError:
            raise
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("PROVIDER_SCHEMA", "Provider response did not match the expected schema.", usage_unknown=True) from exc
        return ProviderResult(
            text=text[: max_output_tokens * 8],
            provider=self.name,
            model=str(payload.get("model", self.model)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            request_id=str(payload.get("id")) if payload.get("id") else None,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
