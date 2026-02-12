from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def _run_git(args: list[str], cwd: str | None) -> tuple[int, str, str]:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        shell=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def make_git_status_tool() -> Tool:
    spec = ToolSpec(
        id="git.status",
        name="Git Status",
        description="Get git status (porcelain).",
        inputs_schema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
            },
            "required": ["repo_path"],
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        repo = str(inputs["repo_path"])
        try:
            repo_p = Path(repo).expanduser().resolve()
            rc, out, err = _run_git(["status", "--porcelain=v1", "-b"], cwd=str(repo_p))
            return ToolResult(
                status="ok" if rc == 0 else "error",
                stdout=out,
                stderr=err,
                artifacts={"repo_path": str(repo_p), "returncode": rc},
            )
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)


def make_git_diff_tool() -> Tool:
    spec = ToolSpec(
        id="git.diff",
        name="Git Diff",
        description="Get git diff (optionally staged).",
        inputs_schema={
            "type": "object",
            "properties": {
                "repo_path": {"type": "string"},
                "staged": {"type": "boolean"},
                "paths": {"type": "array", "items": {"type": "string"}},
                "max_bytes": {"type": "integer", "minimum": 1, "maximum": 5_000_000},
            },
            "required": ["repo_path"],
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        repo = str(inputs["repo_path"])
        staged = bool(inputs.get("staged", False))
        paths = list(inputs.get("paths") or [])
        max_bytes = int(inputs.get("max_bytes", 400_000))
        try:
            repo_p = Path(repo).expanduser().resolve()
            args = ["diff"]
            if staged:
                args.append("--staged")
            if paths:
                args.append("--")
                args.extend(paths)
            rc, out, err = _run_git(args, cwd=str(repo_p))
            if len(out.encode("utf-8", errors="ignore")) > max_bytes:
                out = out.encode("utf-8", errors="ignore")[:max_bytes].decode("utf-8", errors="replace")
                out += "\n...(truncated)...\n"
            return ToolResult(
                status="ok" if rc == 0 else "error",
                stdout=out,
                stderr=err,
                artifacts={"repo_path": str(repo_p), "returncode": rc, "staged": staged},
            )
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)

