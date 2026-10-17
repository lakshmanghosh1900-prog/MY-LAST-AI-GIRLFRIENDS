"""Static, least-privilege registry for the currently enabled read-only tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class ToolRegistryError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ToolExecutionError(RuntimeError):
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


def execute_registered_tool(name: str, arguments: dict, *, file_tool, web_tool) -> dict:
    """Execute only the fixed read-only handlers declared by the registry."""

    spec = get_tool(name)
    spec.validate(arguments)
    try:
        if name == "file.read_text":
            result = file_tool.read_text(arguments["path"])
            return {"name": name, "text": result.text, "source_url": None, "data_class": "SENSITIVE"}
        if name == "web.fetch":
            result = web_tool.fetch(arguments["url"])
            return {"name": name, "text": result.text, "source_url": result.url, "data_class": "PUBLIC"}
    except Exception as exc:
        code = getattr(exc, "code", "TOOL_EXECUTION_FAILED")
        raise ToolExecutionError(code, str(exc)) from exc
    raise ToolExecutionError("TOOL_NOT_ALLOWLISTED", "The requested tool is not registered.")
