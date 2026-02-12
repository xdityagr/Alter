from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .base import Tool, ToolResult, ToolSpec


def make_text_search_tool() -> Tool:
    spec = ToolSpec(
        id="text.search",
        name="Search In Files",
        description="Search for a query string in files under a root folder (uses ripgrep if available).",
        inputs_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "root": {"type": "string"},
                "glob": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 5000},
            },
            "required": ["query", "root"],
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        query = str(inputs["query"])
        root = Path(str(inputs["root"])).expanduser()
        glob = inputs.get("glob")
        max_results = int(inputs.get("max_results", 200))

        try:
            root = root.resolve()
            matches = _search_rg(query=query, root=root, glob=glob, max_results=max_results)
            if matches is None:
                matches = _search_python(query=query, root=root, glob=glob, max_results=max_results)
            return ToolResult(status="ok", artifacts={"matches": matches, "root": str(root)})
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)


def _search_rg(
    *, query: str, root: Path, glob: str | None, max_results: int
) -> list[dict[str, Any]] | None:
    """
    Try ripgrep if installed. Returns None if rg isn't available.
    """
    try:
        subprocess.run(["rg", "--version"], capture_output=True, text=True, timeout=5, shell=False)
    except Exception:
        return None

    # Use --json to avoid Windows drive-letter ":" parsing issues.
    args = ["rg", "--json", "--fixed-strings", query, str(root)]
    if glob:
        args.extend(["-g", str(glob)])

    completed = subprocess.run(args, capture_output=True, text=True, timeout=60, shell=False)
    if completed.returncode not in (0, 1):
        # 0: matches found, 1: no matches
        raise RuntimeError(completed.stderr.strip() or "rg failed")

    out: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        if len(out) >= max_results:
            break
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") != "match":
            continue
        data = obj.get("data") or {}
        path = ((data.get("path") or {}).get("text")) if isinstance(data.get("path"), dict) else None
        line_no = data.get("line_number")
        lines = (data.get("lines") or {}).get("text") if isinstance(data.get("lines"), dict) else ""
        out.append({"path": path, "line": line_no, "text": (lines or "").rstrip("\n")})
    return out


def _iter_files(root: Path, glob: str | None) -> Iterable[Path]:
    if glob:
        yield from root.rglob(glob)
        return
    for p in root.rglob("*"):
        yield p


def _search_python(
    *, query: str, root: Path, glob: str | None, max_results: int
) -> list[dict[str, Any]]:
    """
    Slow fallback search (substring) for when ripgrep isn't present.
    """
    out: list[dict[str, Any]] = []
    q = query

    for p in _iter_files(root, glob):
        if len(out) >= max_results:
            break
        try:
            if not p.is_file():
                continue
            # Skip obviously huge files.
            if p.stat().st_size > 2_000_000:
                continue
            # Skip binary-ish files.
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".exe", ".dll"}:
                continue

            text = p.read_text(encoding="utf-8", errors="ignore")
            for i, line in enumerate(text.splitlines(), start=1):
                if q in line:
                    out.append({"path": str(p), "line": i, "text": line})
                    if len(out) >= max_results:
                        break
        except (OSError, UnicodeError):
            continue

    return out
