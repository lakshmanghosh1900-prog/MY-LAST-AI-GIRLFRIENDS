"""Durable one-shot local reminders with deterministic idempotent runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


class SchedulerError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScheduleSpec:
    title: str
    prompt: str
    run_at: str


def normalize_run_at(value: str) -> str:
    if not isinstance(value, str) or len(value) > 64:
        raise SchedulerError("SCHEDULE_TIME_INVALID", "run_at must be an ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise SchedulerError("SCHEDULE_TIME_INVALID", "run_at must be an ISO timestamp.") from exc
    if parsed.tzinfo is None:
        raise SchedulerError("SCHEDULE_TIMEZONE_REQUIRED", "run_at must include a timezone.")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_schedule(title: str, prompt: str, run_at: str, max_chars: int) -> ScheduleSpec:
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise SchedulerError("SCHEDULE_TITLE_INVALID", "title is required and must be short.")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > max_chars:
        raise SchedulerError("SCHEDULE_PROMPT_INVALID", "prompt is required and must fit the configured limit.")
    return ScheduleSpec(title.strip(), prompt.strip(), normalize_run_at(run_at))
