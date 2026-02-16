from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_fs_read_tool() -> Tool:
    spec = ToolSpec(
        id="fs.read",
        name="Read File",
        description="Read a UTF-8 text file from disk. Supports reading specific line ranges.",
        inputs_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "minimum": 1, "description": "1-indexed start line (inclusive)."},
                "end_line": {"type": "integer", "minimum": 1, "description": "1-indexed end line (inclusive)."},
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
        start_line = inputs.get("start_line")
        end_line = inputs.get("end_line")

        try:
            if not p.exists():
                return ToolResult(status="error", stderr=f"File not found: {p}")
            
            # If line range requested, we must read text
            if start_line is not None or end_line is not None:
                text = p.read_text(encoding="utf-8", errors="replace")
                lines = text.splitlines()
                total_lines = len(lines)
                
                start = (start_line - 1) if start_line else 0
                end = end_line if end_line else total_lines
                
                # Clamp
                start = max(0, start)
                end = min(total_lines, end)
                
                if start >= end:
                    return ToolResult(status="ok", stdout="")
                
                subset = lines[start:end]
                # Rejoin
                content = "\n".join(subset)
                # Check byte limit on the subset
                if len(content) > max_bytes:
                     content = content[:max_bytes] + "\n...(truncated bytes)..."
                
                return ToolResult(status="ok", stdout=content)

            # Normal byte read
            data = p.read_bytes()
            if len(data) > max_bytes:
                data = data[:max_bytes]
            text = data.decode("utf-8", errors="replace")
            return ToolResult(status="ok", stdout=text)
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)


def make_fs_read_multiple_tool() -> Tool:
    spec = ToolSpec(
        id="fs.read_multiple",
        name="Read Multiple Files",
        description="Read content of multiple files at once. Good for context gathering.",
        inputs_schema={
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 10
                },
                "max_bytes_per_file": {"type": "integer", "default": 10000}
            },
            "required": ["paths"],
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        paths = inputs["paths"]
        max_bytes = int(inputs.get("max_bytes_per_file", 10000))
        
        results = {}
        errors = []
        
        for p_str in paths:
            try:
                p = Path(p_str).expanduser()
                if not p.exists():
                    errors.append(f"{p_str}: Not found")
                    continue
                if not p.is_file():
                    errors.append(f"{p_str}: Not a file")
                    continue
                    
                data = p.read_bytes()
                if len(data) > max_bytes:
                    text = data[:max_bytes].decode("utf-8", errors="replace") + "\n...(truncated)..."
                else:
                    text = data.decode("utf-8", errors="replace")
                
                results[str(p)] = text
            except Exception as e:
                errors.append(f"{p_str}: {e}")

        # Format output
        out_lines = []
        if results:
            for fpath, content in results.items():
                out_lines.append(f"--- FILE: {fpath} ---")
                out_lines.append(content)
                out_lines.append("\n")
        
        if errors:
            out_lines.append("--- ERRORS ---")
            out_lines.extend(errors)

        output = "\n".join(out_lines)
        status = "ok" if not errors else ("error" if not results else "ok")
        
        return ToolResult(status=status, stdout=output)

    return Tool(spec=spec, action=action)


def make_fs_list_tool() -> Tool:
    spec = ToolSpec(
        id="fs.list",
        name="List Directory",
        description="List a directory (optionally recursive).",
        inputs_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean"},
                "max_depth": {"type": "integer", "minimum": 1, "maximum": 20},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 5000},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        root_path = Path(inputs["path"]).expanduser()
        max_entries = int(inputs.get("max_entries", 200))
        recursive = bool(inputs.get("recursive", False))
        max_depth = int(inputs.get("max_depth", 1)) if recursive else 1
        
        # Default exclusions to prevent context flooding
        EXCLUDED_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", ".venv", "venv", ".idea", ".vscode"}

        entries = []
        
        def _scan(p: Path, current_depth: int):
            if len(entries) >= max_entries:
                return
                
            try:
                # specific sort for stability: directories first, then files, then name
                items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except (OSError, PermissionError):
                return

            for child in items:
                if len(entries) >= max_entries:
                    return
                    
                is_dir = child.is_dir()
                entries.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "is_dir": is_dir,
                        "is_file": child.is_file(),
                        "rel_path": str(child.relative_to(root_path))
                    }
                )
                
                # Recurse if directory, within depth limit, and NOT in excluded list
                if recursive and is_dir and current_depth < max_depth:
                    if child.name in EXCLUDED_DIRS:
                        continue
                    _scan(child, current_depth + 1)

        try:
            if not root_path.exists():
                 return ToolResult(status="error", stderr=f"Path not found: {root_path}")
            
            _scan(root_path, 1)
            return ToolResult(status="ok", stdout="", artifacts={"entries": entries})
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)


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


def make_fs_edit_tool(*, allowed_roots: list[str], require_confirmation: bool) -> Tool:
    roots_txt = ", ".join(allowed_roots) if allowed_roots else "(none)"
    spec = ToolSpec(
        id="fs.edit",
        name="Edit File",
        description=(
            "Surgically edit a file by replacing exact text OR by line numbers. "
            f"Allowed roots: {roots_txt}."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "type": {"type": "string", "enum": ["text", "lines"], "description": "Edit mode: 'text' (default) or 'lines'."},
                "target_text": {"type": "string", "description": "The EXACT text block to find and replace. Must be unique in the file."},
                "replacement_text": {"type": "string", "description": "The new text to insert."},
                "start_line": {"type": "integer", "minimum": 1, "description": "1-indexed start line (inclusive)."},
                "end_line": {"type": "integer", "minimum": 1, "description": "1-indexed end line (inclusive)."},
            },
            "required": ["path", "replacement_text"],
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
        p = Path(inputs["path"]).expanduser()
        edit_type = inputs.get("type", "text")
        replacement = inputs.get("replacement_text", "")
        
        if not _is_allowed(p):
             return ToolResult(status="error", stderr=f"Edit blocked. Path outside allowed roots: {p}")
        
        if not p.exists():
            return ToolResult(status="error", stderr=f"File not found: {p}")

        try:
            content = p.read_text(encoding="utf-8")
        except Exception as e:
             return ToolResult(status="error", stderr=f"Failed to read file: {e}")

        new_content = content

        if edit_type == "text":
            target = inputs.get("target_text")
            if not target:
                return ToolResult(status="error", stderr="Missing `target_text` for text mode edit.")
            
            # Normalize line endings for robust matching?
            # For now, strict match.
            count = content.count(target)
            if count == 0:
                return ToolResult(status="error", stderr="Target text NOT found in file. Check indentation and exact characters.")
            if count > 1:
                return ToolResult(status="error", stderr=f"Target text found {count} times. Ambiguous edit. Use 'lines' mode or provide more unique context.")
            
            new_content = content.replace(target, replacement)
        
        elif edit_type == "lines":
            start_line = inputs.get("start_line")
            end_line = inputs.get("end_line")
            
            if start_line is None or end_line is None:
                 return ToolResult(status="error", stderr="Missing `start_line` or `end_line` for lines mode edit.")
            
            # Detect newline style
            newline = "\n"
            if "\r\n" in content: newline = "\r\n"
            
            lines_clean = content.splitlines()
            s_idx = max(0, start_line - 1)
            e_idx = min(len(lines_clean), end_line)
            
            if s_idx > e_idx:
                 return ToolResult(status="error", stderr=f"Invalid line range: {start_line}-{end_line}")

            before = lines_clean[:s_idx]
            after = lines_clean[e_idx:]
            
            # Handle replacement text lines
            rep_lines = replacement.splitlines()
            
            final_lines = before + rep_lines + after
            new_content = newline.join(final_lines)
            
            # Preserve trailing newline logic if original had it
            if content.endswith(newline) and not new_content.endswith(newline):
                new_content += newline
                
        else:
             return ToolResult(status="error", stderr=f"Unknown edit type: {edit_type}")

        try:
            p.write_text(new_content, encoding="utf-8")
            return ToolResult(status="ok", stdout=f"Successfully edited {p.name}")
        except Exception as e:
            return ToolResult(status="error", stderr=f"Failed to write file: {e}")

    return Tool(spec=spec, action=action)

