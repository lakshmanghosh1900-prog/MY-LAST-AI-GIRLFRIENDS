"""Explicit service lifecycle and safe-stop behavior."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass
class Lifecycle:
    state: str = "STARTING"

    def __post_init__(self) -> None:
        self._lock = Lock()

    def ready(self) -> None:
        with self._lock:
            if self.state not in {"STARTING", "STOPPED"}:
                raise RuntimeError(f"cannot enter READY from {self.state}")
            self.state = "READY"

    def begin_stop(self) -> bool:
        with self._lock:
            if self.state in {"DRAINING", "STOPPED"}:
                return False
            self.state = "DRAINING"
            return True

    def stopped(self) -> None:
        with self._lock:
            self.state = "STOPPED"

    def can_accept_work(self) -> bool:
        with self._lock:
            return self.state == "READY"

    def snapshot(self) -> str:
        with self._lock:
            return self.state
