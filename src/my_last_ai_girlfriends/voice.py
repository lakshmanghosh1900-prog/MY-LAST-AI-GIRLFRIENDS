"""Voice provider contracts shared by supported browser/device clients.

The server does not fabricate transcripts or audio. The browser implementation
uses its native Web Speech APIs when available and reports unsupported devices
explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class VoiceError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SpeechInputProvider(Protocol):
    def start(self) -> None: ...
    def cancel(self) -> None: ...


class SpeechOutputProvider(Protocol):
    def speak(self, text: str) -> None: ...
    def cancel(self) -> None: ...


@dataclass(frozen=True)
class VoiceCapability:
    input_supported: bool
    output_supported: bool
    provider: str
    reason: str


def normalize_transcript(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise VoiceError("VOICE_TRANSCRIPT_EMPTY", "Speech input did not contain a transcript.")
    return " ".join(value.split())[:12000]


def unsupported_voice_capability(reason: str = "A browser speech provider is unavailable.") -> VoiceCapability:
    return VoiceCapability(False, False, "none", reason)
