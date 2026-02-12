from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_fs_write_tool(*, allowed_roots: list[str], require_confirmation: bool) -> Tool:
    roots_txt = ", ".join(allowed_roots) if allowed_roots else "(none)"
    spec = ToolSpec(
        id="fs.write",
        name="Write File",
        description=(
            "Write a UTF-8 text file to disk (restricted to allowed roots). "
            f"Confirmation is required. Allowed roots: {roots_txt}. "
            "Prefer a relative path like `notes/todo.txt`."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "mode": {"type": "string", "enum": ["overwrite", "append"]},
                "create_parents": {"type": "boolean"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        confirm=require_confirmation,
    )

    roots = [Path(r).expanduser().resolve() for r in allowed_roots] if allowed_roots else []

    def _is_allowed(p: Path) -> bool:
        if not roots:
            return False
        p = p.resolve()
        return any((root == p) or (root in p.parents) for root in roots)

    def action(inputs: dict[str, Any]) -> ToolResult:
        try:
            p = Path(inputs["path"]).expanduser()
            mode = str(inputs.get("mode") or "overwrite")
            create_parents = bool(inputs.get("create_parents", True))
            content = str(inputs.get("content") or "")

            if not _is_allowed(p):
                return ToolResult(
                    status="error",
                    stderr=f"Write blocked. Path is outside allowed roots: {p}. Allowed: {[str(r) for r in roots]}",
                )

            if create_parents:
                p.parent.mkdir(parents=True, exist_ok=True)

            if mode == "append":
                with p.open("a", encoding="utf-8", errors="strict", newline="") as f:
                    f.write(content)
                return ToolResult(status="ok", artifacts={"path": str(p), "mode": "append"})

            # overwrite (default)
            p.write_text(content, encoding="utf-8", errors="strict", newline="")
            return ToolResult(status="ok", artifacts={"path": str(p), "mode": "overwrite"})
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)
