"""Versioned deterministic evaluation cases for the bounded companion slice."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from dataclasses import replace
from pathlib import Path


EVALUATION_VERSION = "local-companion-eval-0.1.0"


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class EvaluationReport:
    version: str
    cases: tuple[EvaluationCase, ...]

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "passed": self.passed,
            "cases": [{"name": case.name, "passed": case.passed, "detail": case.detail} for case in self.cases],
        }


def run_local_evaluation(service) -> EvaluationReport:
    # Evaluations are disposable fixtures; never contaminate the caller's data.
    from .service import MyLastAIGirlfriendsService

    with tempfile.TemporaryDirectory(prefix="mlag-eval-") as raw:
        root = Path(raw)
        isolated_config = replace(service.config, mode="offline", data_dir=root / "data", allowed_root=root / "workspace")
        isolated = MyLastAIGirlfriendsService(isolated_config)
        try:
            conversation = isolated.create_conversation()
            offline = isolated.handle_message(conversation, "evaluation local response")
            blocked = isolated.handle_message(conversation, "my password is evaluation-secret")
            memory = isolated.create_memory("Evaluation preference: concise")
            cases = (
                EvaluationCase("offline_truthful_label", not offline.ai_generated and "Offline demo" in offline.message, offline.status),
                EvaluationCase("prohibited_input_safe_stop", blocked.status == "SAFE_STOP", blocked.status),
                EvaluationCase("explicit_memory_created", bool(memory.get("id")) and memory.get("confirmed") is True, "confirmed"),
            )
            return EvaluationReport(EVALUATION_VERSION, cases)
        finally:
            isolated.close()
