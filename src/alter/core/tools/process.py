from __future__ import annotations

import os
import platform
import subprocess
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_process_list_tool() -> Tool:
    spec = ToolSpec(
        id="process.list",
        name="List Processes",
        description=(
            "List running processes on the system, optionally filtered by name. "
            "Returns PID, name, and status. Use this to verify if a service or app is running "
            "instead of guessing."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Optional substring to filter process names (case-insensitive). Leave empty for all.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Max number of processes to return. Default 30.",
                },
            },
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        name_filter = str(inputs.get("filter", "")).strip().lower()
        limit = int(inputs.get("limit", 30))

        try:
            system = platform.system()
            if system == "Windows":
                # Use tasklist for reliable process listing
                result = subprocess.run(
                    ["tasklist", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode != 0:
                    return ToolResult(status="error", stderr=result.stderr or "tasklist failed")

                lines = []
                for row in result.stdout.strip().splitlines():
                    # CSV format: "name.exe","PID","Session","Session#","Mem Usage"
                    parts = [p.strip('"') for p in row.split('","')]
                    if len(parts) >= 5:
                        name = parts[0]
                        pid = parts[1]
                        mem = parts[4]
                        if name_filter and name_filter not in name.lower():
                            continue
                        lines.append(f"{pid:>8}  {mem:>12}  {name}")
                        if len(lines) >= limit:
                            break

                if not lines:
                    msg = f"No processes found matching '{name_filter}'." if name_filter else "No processes found."
                    return ToolResult(status="ok", stdout=msg)

                header = f"{'PID':>8}  {'Memory':>12}  Name"
                output = header + "\n" + "-" * 50 + "\n" + "\n".join(lines)
                return ToolResult(
                    status="ok",
                    stdout=output,
                    artifacts={"count": len(lines), "filter": name_filter or "(all)"},
                )

            else:
                # Unix: use ps
                result = subprocess.run(
                    ["ps", "aux", "--sort=-rss"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                lines = result.stdout.strip().splitlines()
                if name_filter:
                    lines = [lines[0]] + [l for l in lines[1:] if name_filter in l.lower()]
                output = "\n".join(lines[: limit + 1])
                return ToolResult(status="ok", stdout=output, artifacts={"count": len(lines) - 1})

        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)
