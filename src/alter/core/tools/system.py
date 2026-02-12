from __future__ import annotations

import os
import platform
import socket
from pathlib import Path
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_system_info_tool() -> Tool:
    spec = ToolSpec(
        id="system.info",
        name="System Info",
        description="Return basic system information (OS, python, machine).",
        inputs_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        info = {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "python_version": platform.python_version(),
        }
        return ToolResult(status="ok", artifacts=info)

    return Tool(spec=spec, action=action)


def make_system_snapshot_tool() -> Tool:
    spec = ToolSpec(
        id="system.snapshot",
        name="System Snapshot",
        description=(
            "Collect a safe, non-secret snapshot of this machine (paths, OS, drives, common folders, repos)."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "roots": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional scan roots for git repos (paths). Defaults to common dev folders.",
                },
                "max_depth": {"type": "integer", "default": 4, "minimum": 1, "maximum": 8},
                "max_repos": {"type": "integer", "default": 30, "minimum": 1, "maximum": 200},
                "list_home_dirs": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
        confirm=False,
    )

    def _safe_list_dir(p: Path, limit: int = 60) -> list[str]:
        try:
            items = []
            for entry in p.iterdir():
                if entry.name.startswith("."):
                    continue
                if entry.is_dir():
                    items.append(entry.name + "/")
                else:
                    items.append(entry.name)
                if len(items) >= limit:
                    break
            return sorted(items)
        except Exception:
            return []

    def _default_roots(home: Path, cwd: Path) -> list[Path]:
        candidates = [
            cwd,
            home / "Projects",
            home / "Desktop",
            home / "Documents",
            home / "Downloads",
        ]
        out: list[Path] = []
        for c in candidates:
            try:
                if c.exists() and c.is_dir():
                    out.append(c)
            except Exception:
                continue
        # De-dup
        seen = set()
        uniq = []
        for p in out:
            s = str(p.resolve())
            if s in seen:
                continue
            seen.add(s)
            uniq.append(p)
        return uniq

    def _list_drives() -> list[str]:
        sysname = platform.system().lower()
        if "windows" in sysname:
            drives = []
            for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                root = Path(f"{c}:\\")
                try:
                    if root.exists():
                        drives.append(str(root))
                except Exception:
                    continue
            return drives
        # Unix-ish: just report / and /mnt if present
        out = ["/"]
        if Path("/mnt").exists():
            out.append("/mnt")
        return out

    def _find_git_repos(roots: list[Path], max_depth: int, max_repos: int) -> list[str]:
        repos: list[str] = []
        max_repos = max(1, max_repos)
        for root in roots:
            root = root.expanduser()
            if not root.exists() or not root.is_dir():
                continue
            root_str = str(root)
            for dirpath, dirnames, filenames in os.walk(root_str):
                if len(repos) >= max_repos:
                    return repos
                # Depth pruning
                try:
                    rel = Path(dirpath).relative_to(root)
                    depth = len(rel.parts)
                except Exception:
                    depth = 0
                if depth > max_depth:
                    dirnames[:] = []
                    continue

                if ".git" in dirnames:
                    repos.append(dirpath)
                    # Don't recurse into repos
                    dirnames[:] = []
                    continue

                # Skip typical heavy folders
                skip = {".venv", "venv", "node_modules", ".git", "__pycache__", "dist", "build"}
                dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]

        return repos

    def action(inputs: dict[str, Any]) -> ToolResult:
        home = Path.home()
        cwd = Path.cwd()
        desktop = home / "Desktop"
        downloads = home / "Downloads"
        documents = home / "Documents"
        projects = home / "Projects"

        roots_in = inputs.get("roots") or []
        max_depth = int(inputs.get("max_depth", 4))
        max_repos = int(inputs.get("max_repos", 30))
        list_home_dirs = bool(inputs.get("list_home_dirs", True))

        roots: list[Path]
        if roots_in:
            roots = [Path(r) for r in roots_in if r]
        else:
            roots = _default_roots(home, cwd)

        repos = _find_git_repos(roots, max_depth=max_depth, max_repos=max_repos)

        artifacts = {
            "os": {
                "platform": platform.platform(),
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python_version": platform.python_version(),
            },
            "host": {
                "hostname": socket.gethostname(),
            },
            "paths": {
                "cwd": str(cwd),
                "home": str(home),
                "desktop": str(desktop),
                "downloads": str(downloads),
                "documents": str(documents),
                "projects": str(projects),
            },
            "drives": _list_drives(),
            "roots_scanned": [str(p) for p in roots],
            "git_repos": repos,
        }

        if list_home_dirs:
            artifacts["home_listing"] = _safe_list_dir(home)

        stdout = (
            f"hostname={artifacts['host']['hostname']}\n"
            f"os={artifacts['os']['system']} {artifacts['os']['release']}\n"
            f"projects={artifacts['paths']['projects']}\n"
            f"repos_found={len(repos)}"
        )
        return ToolResult(status="ok", stdout=stdout, artifacts=artifacts)

    return Tool(spec=spec, action=action)
