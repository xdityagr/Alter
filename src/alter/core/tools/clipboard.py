from __future__ import annotations

import subprocess
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_clipboard_read_tool() -> Tool:
    spec = ToolSpec(
        id="clipboard.read",
        name="Read Clipboard",
        description="Read user's clipboard content as text.",
        inputs_schema={
            "type": "object",
            "properties": {},
            "required": [],
        },
        confirm=False,
    )

    def action(_: dict[str, Any]) -> ToolResult:
        try:
            # Use PowerShell to read clipboard
            # Ensure we get raw text
            cmd = ["powershell", "-NoProfile", "-Command", "Get-Clipboard"]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return ToolResult(status="ok", stdout=proc.stdout.strip())
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)


def make_clipboard_write_tool() -> Tool:
    spec = ToolSpec(
        id="clipboard.write",
        name="Write Clipboard",
        description="Copy text to user's clipboard.",
        inputs_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Text to copy"},
            },
            "required": ["content"],
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        content = inputs.get("content", "")
        try:
            # Use PowerShell to write clipboard
            # pipe content to Set-Clipboard
            cmd = ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"]
            proc = subprocess.run(cmd, input=content, capture_output=True, text=True, check=True)
            return ToolResult(status="ok", stdout="Copied to clipboard.")
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)
