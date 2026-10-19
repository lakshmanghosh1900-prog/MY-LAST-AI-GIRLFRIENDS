"""Bounded local role orchestration without expanding capabilities."""

from __future__ import annotations

from dataclasses import dataclass


class OrchestrationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


ROLES = ("planner", "researcher", "executor", "verifier", "composer")


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    status: str
    roles: tuple[str, ...]
    depth: int
    capability_set: tuple[str, ...]
    evidence: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "execution_mode": "local_deterministic",
            "ai_generated": False,
            "roles": list(self.roles),
            "depth": self.depth,
            "capability_set": list(self.capability_set),
            "evidence": list(self.evidence),
        }


def run_bounded_local_pipeline(run_id: str, prompt: str, max_depth: int = 1, max_roles: int = 5) -> AgentRun:
    if not isinstance(prompt, str) or not prompt.strip():
        raise OrchestrationError("AGENT_PROMPT_REQUIRED", "A bounded agent prompt is required.")
    if (
        not isinstance(max_depth, int)
        or isinstance(max_depth, bool)
        or not isinstance(max_roles, int)
        or isinstance(max_roles, bool)
        or max_depth < 0
        or max_depth > 3
        or max_roles < 1
        or max_roles > len(ROLES)
    ):
        raise OrchestrationError("AGENT_LIMIT_INVALID", "Agent limits must be integers within the safe local bounds.")
    roles = ROLES[:max_roles]
    evidence = ("planner: bounded local plan created", "verifier: no new capability granted")
    return AgentRun(run_id, "SUCCEEDED", roles, max_depth, ("read-only-file", "public-fetch"), evidence)
