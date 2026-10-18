"""Durable one-shot local reminders with deterministic idempotent runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from typing import Callable


class SchedulerError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScheduleSpec:
    title: str
    prompt: str
    run_at: str
    recurrence: str = "once"


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


def next_run_at(value: str, recurrence: str) -> str:
    """Calculate the next UTC occurrence using an explicit UTC policy.

    Recurring schedules intentionally use fixed UTC intervals. This avoids
    silently changing local wall-clock behavior across DST transitions.
    """

    normalized = normalize_run_at(value)
    intervals = {"hourly": timedelta(hours=1), "daily": timedelta(days=1), "weekly": timedelta(days=7)}
    if recurrence not in intervals:
        raise SchedulerError("SCHEDULE_RECURRENCE_INVALID", "recurrence must be once, hourly, daily or weekly.")
    return (datetime.fromisoformat(normalized.replace("Z", "+00:00")) + intervals[recurrence]).isoformat(timespec="microseconds").replace("+00:00", "Z")


def validate_schedule(title: str, prompt: str, run_at: str, max_chars: int, recurrence: str = "once") -> ScheduleSpec:
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        raise SchedulerError("SCHEDULE_TITLE_INVALID", "title is required and must be short.")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > max_chars:
        raise SchedulerError("SCHEDULE_PROMPT_INVALID", "prompt is required and must fit the configured limit.")
    if recurrence not in {"once", "hourly", "daily", "weekly"}:
        raise SchedulerError("SCHEDULE_RECURRENCE_INVALID", "recurrence must be once, hourly, daily or weekly.")
    return ScheduleSpec(title.strip(), prompt.strip(), normalize_run_at(run_at), recurrence)


class SchedulerWorker:
    """Restart-safe polling lifecycle for local schedules.

    The worker owns no schedule state. Every tick reloads durable state through
    the service callback, so process restart resumes from SQLite. Errors are
    reported to the callback and do not create automatic retries for a failed
    occurrence.
    """

    def __init__(self, tick: Callable[[], object], interval_seconds: int = 30, on_error: Callable[[Exception], None] | None = None):
        if not isinstance(interval_seconds, int) or interval_seconds < 1 or interval_seconds > 3600:
            raise SchedulerError("SCHEDULER_INTERVAL_INVALID", "scheduler interval must be between 1 and 3600 seconds.")
        self._tick = tick
        self._interval_seconds = interval_seconds
        self._on_error = on_error
        self._stop = Event()
        self._thread: Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as exc:  # worker remains alive; occurrence errors are durable elsewhere
                if self._on_error:
                    self._on_error(exc)
            self._stop.wait(self._interval_seconds)

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="mlag-scheduler", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        self._thread = None
