from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult, ToolSpec


@dataclass(frozen=True)
class ShellPolicy:
    allowed_programs: set[str]
    require_confirmation: bool


def make_shell_tool(policy: ShellPolicy) -> Tool:
    spec = ToolSpec(
        id="shell.run",
        name="Run Command",
        description=(
            "Run an allowlisted executable with arguments. "
            "This is confirmation-gated by default."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "program": {"type": "string"},
                "args": {"type": "array", "items": {"type": "string"}},
                "cwd": {"type": ["string", "null"]},
                "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600},
            },
            "required": ["program"],
            "additionalProperties": False,
        },
        confirm=policy.require_confirmation,
    )

    allowed_norm = {p.lower() for p in policy.allowed_programs}

    def action(inputs: dict[str, Any]) -> ToolResult:
        program = inputs["program"]
        args = list(inputs.get("args") or [])
        cwd = inputs.get("cwd") or None  # Treat empty string as None
        timeout_s = int(inputs.get("timeout_s", 60))

        program_norm = Path(program).name.lower()
        if program_norm not in allowed_norm:
            return ToolResult(
                status="error",
                stderr=f"Program not allowlisted: {program_norm}. Allowed: {sorted(policy.allowed_programs)}",
            )

        # When shell=True on Windows, we must pass the command as a string,
        # otherwise arguments after the executable are treated as arguments to cmd.exe, not the program.
        # We use list2cmdline to properly quote arguments.
        command_str = subprocess.list2cmdline([program, *args])

        try:
            completed = subprocess.run(
                command_str,
                cwd=cwd,
                capture_output=True,
                text=True,
                encoding="utf-8", 
                errors="replace",
                timeout=timeout_s,
                shell=True,
                input="", # Close stdin immediately to prevent hanging on prompts
            )
            # Powershell sometimes uses non-utf8 defaults, explicit encoding helps.
            # Powershell sometimes uses non-utf8 defaults, explicit encoding helps.
            out = completed.stdout or ""
            err = completed.stderr or ""
            return ToolResult(
                status="ok" if completed.returncode == 0 else "error",
                stdout=out,
                stderr=err,
                artifacts={"returncode": completed.returncode, "stdout_len": len(out)},
            )
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)

