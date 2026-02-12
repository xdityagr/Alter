from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_fs_read_tool() -> Tool:
    spec = ToolSpec(
        id="fs.read",
        name="Read File",
        description="Read a UTF-8 text file from disk.",
        inputs_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 5_000_000},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        p = Path(inputs["path"]).expanduser()
        max_bytes = int(inputs.get("max_bytes", 200_000))
        try:
            data = p.read_bytes()
            if len(data) > max_bytes:
                data = data[:max_bytes]
            text = data.decode("utf-8", errors="replace")
            return ToolResult(status="ok", stdout=text)
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)


def make_fs_list_tool() -> Tool:
    spec = ToolSpec(
        id="fs.list",
        name="List Directory",
        description="List a directory (non-recursive).",
        inputs_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 5000},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        p = Path(inputs["path"]).expanduser()
        max_entries = int(inputs.get("max_entries", 200))
        try:
            entries = []
            for i, child in enumerate(p.iterdir()):
                if i >= max_entries:
                    break
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "is_dir": child.is_dir(),
                        "is_file": child.is_file(),
                    }
                )
            return ToolResult(status="ok", stdout="", artifacts={"entries": entries})
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)

