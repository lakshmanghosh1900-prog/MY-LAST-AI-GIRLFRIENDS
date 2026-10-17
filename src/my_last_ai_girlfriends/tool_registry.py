"""Static, least-privilege registry for the currently enabled read-only tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class ToolRegistryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ToolSpec:
    name: str
    capability: str
    argument_names: frozenset[str]
    required_arguments: frozenset[str]
    read_only: bool

    def validate(self, arguments: dict) -> None:
        if not isinstance(arguments, dict):
            raise ToolRegistryError("TOOL_ARGUMENTS_INVALID", "Tool arguments must be an object.")
        missing = self.required_arguments - arguments.keys()
        if missing:
            raise ToolRegistryError("TOOL_ARGUMENT_REQUIRED", "Required tool arguments are missing.")
        unknown = set(arguments) - self.argument_names
        if unknown:
            raise ToolRegistryError("TOOL_ARGUMENT_UNKNOWN", "Unknown tool arguments are not allowed.")


REGISTRY: dict[str, ToolSpec] = {
    "file.read_text": ToolSpec("file.read_text", "read approved local text", frozenset({"path"}), frozenset({"path"}), True),
    "web.fetch": ToolSpec("web.fetch", "fetch bounded public HTTPS text", frozenset({"url"}), frozenset({"url"}), True),
}


def get_tool(name: str) -> ToolSpec:
    try:
        return REGISTRY[name]
    except KeyError as exc:
        raise ToolRegistryError("TOOL_NOT_ALLOWLISTED", "The requested tool is not registered.") from exc


def list_tools() -> list[dict]:
    return [
        {"name": spec.name, "capability": spec.capability, "read_only": spec.read_only}
        for spec in REGISTRY.values()
    ]
