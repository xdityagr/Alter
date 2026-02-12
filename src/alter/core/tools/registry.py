from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .base import Tool, ToolResult


@dataclass
class ToolRegistry:
    _tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.spec.id in self._tools:
            raise ValueError(f"Tool already registered: {tool.spec.id}")
        self._tools[tool.spec.id] = tool

    def list_specs(self) -> list[dict[str, Any]]:
        return [self._as_dict(t) for t in self._tools.values()]

    def get(self, tool_id: str) -> Tool:
        if tool_id not in self._tools:
            raise KeyError(tool_id)
        return self._tools[tool_id]

    def validate_inputs(self, tool_id: str, inputs: dict[str, Any]) -> None:
        tool = self.get(tool_id)
        validator = Draft202012Validator(tool.spec.inputs_schema)
        errors = sorted(validator.iter_errors(inputs), key=lambda e: e.path)
        if errors:
            msg = "; ".join(e.message for e in errors[:3])
            raise ValueError(f"Invalid inputs for {tool_id}: {msg}")

    def execute(self, tool_id: str, inputs: dict[str, Any], on_progress: Callable[[str], None] | None = None) -> ToolResult:
        self.validate_inputs(tool_id, inputs)
        tool = self.get(tool_id)
        sig = inspect.signature(tool.action)
        if "on_progress" in sig.parameters:
            return tool.action(inputs, on_progress=on_progress)
        return tool.action(inputs)

    @staticmethod
    def _as_dict(tool: Tool) -> dict[str, Any]:
        s = tool.spec
        return {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "inputs_schema": s.inputs_schema,
            "confirm": s.confirm,
        }

