from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_fs_rename_tool(*, allowed_roots: list[str], require_confirmation: bool) -> Tool:
    roots_txt = ", ".join(allowed_roots) if allowed_roots else "(none)"
    spec = ToolSpec(
        id="fs.rename",
        name="Rename/Move File",
        description=(
            "Rename or move a file on disk (restricted to allowed roots). "
            f"Confirmation is required. Allowed roots: {roots_txt}."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "src": {"type": "string"},
                "dst": {"type": "string"},
                "overwrite": {"type": "boolean"},
                "create_parents": {"type": "boolean"},
            },
            "required": ["src", "dst"],
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
            src = Path(inputs["src"]).expanduser()
            dst = Path(inputs["dst"]).expanduser()
            overwrite = bool(inputs.get("overwrite", False))
            create_parents = bool(inputs.get("create_parents", True))

            if not _is_allowed(src) or not _is_allowed(dst):
                return ToolResult(
                    status="error",
                    stderr=(
                        "Rename blocked. src/dst must be inside allowed roots.\n"
                        f"src={src}\n"
                        f"dst={dst}\n"
                        f"allowed={[(str(r)) for r in roots]}"
                    ),
                )

            src_r = src.resolve()
            dst_r = dst.resolve()

            if not src_r.exists():
                return ToolResult(status="error", stderr=f"Source does not exist: {src_r}")
            if create_parents:
                dst_r.parent.mkdir(parents=True, exist_ok=True)
            if dst_r.exists() and not overwrite:
                return ToolResult(status="error", stderr=f"Destination already exists: {dst_r}")
            if dst_r.exists() and overwrite:
                dst_r.unlink()

            src_r.replace(dst_r)
            return ToolResult(status="ok", artifacts={"src": str(src_r), "dst": str(dst_r)})
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)

