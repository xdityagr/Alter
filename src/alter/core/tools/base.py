from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    description: str
    # JSONSchema describing `inputs`.
    inputs_schema: dict[str, Any]
    # If true, requires explicit user confirmation before execution.
    confirm: bool


@dataclass(frozen=True)
class ToolResult:
    status: str  # ok | error
    stdout: str = ""
    stderr: str = ""
    artifacts: dict[str, Any] | None = None


ProgressCallback = Callable[[str], None]
ToolAction = Callable[[dict[str, Any], ProgressCallback | None], ToolResult]


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    action: ToolAction

