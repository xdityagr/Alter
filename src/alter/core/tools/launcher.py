from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def _looks_like_path_or_url(target: str) -> bool:
    t = (target or "").strip()
    if not t:
        return False
    tl = t.lower()
    if "://" in t or tl.startswith("www.") or tl.startswith("mailto:"):
        return True
    if os.path.isabs(t):
        return True
    # Drive-letter paths like C:\ or C:/
    if len(t) >= 2 and t[1] == ":":
        return True
    # Any path separators likely indicate a path/relative path
    if "\\" in t or "/" in t:
        return True
    return False


def _normalize_target(target: str) -> str:
    t = str(target or "").strip()
    if not t:
        return t
    if _looks_like_path_or_url(t):
        return t
    # Strip surrounding quotes
    if len(t) >= 2 and t[0] == t[-1] and t[0] in {"'", '"'}:
        t = t[1:-1].strip()
    t = " ".join(t.split())
    original = t
    # Remove polite/verb prefixes iteratively
    for _ in range(2):
        t2 = re.sub(r"^(?:please|pls|plz)[,\s]+", "", t, flags=re.IGNORECASE)
        t2 = re.sub(r"^(?:can|could|would)\s+(?:you|u)[,\s]+", "", t2, flags=re.IGNORECASE)
        t2 = re.sub(
            r"^(?:open|launch|start|run|open up|bring up|show|show me|fire up)\s+",
            "",
            t2,
            flags=re.IGNORECASE,
        )
        t2 = re.sub(r"^the\s+", "", t2, flags=re.IGNORECASE)
        t2 = t2.strip()
        if t2 == t:
            break
        t = t2
    # Remove trailing fluff
    t = re.sub(r"[,\s]*(?:please|thanks|thank you)$", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\b(?:app|application)$", "", t, flags=re.IGNORECASE).strip()
    t = re.sub(r"\bfor me$", "", t, flags=re.IGNORECASE).strip()
    return t or original


def make_launcher_tool(require_confirmation: bool = True) -> Tool:
    spec = ToolSpec(
        id="launcher.open",
        name="Launch App/File",
        description=(
            "Launch an application or open a file using the system's default handler. "
            "Returns immediately."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Absolute path to a file/folder, or the name of an executable (e.g., 'code', 'calc')."
                },
            },
            "required": ["target"],
            "additionalProperties": False,
        },
        confirm=require_confirmation,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        target = _normalize_target(inputs["target"])
        system = platform.system()

        try:
            if system == "Windows":
                import shutil
                
                # Heuristic: If it looks like a relative path but isn't an executable name, hint the user.
                if "\\" in target or "/" in target:
                     if not os.path.exists(target):
                          # Try checking relative to CWD just in case, to give a better error
                          cwd_path = os.path.abspath(target)
                          if os.path.exists(cwd_path):
                              return ToolResult(status="error", stderr=f"File found at '{cwd_path}' but target was relative. Please provide the ABSOLUTE path.")
                          return ToolResult(status="error", stderr=f"File or folder not found: '{target}'. Please check the path and try again.")

                # Helper: Check if runnable
                is_path = os.path.exists(target)
                is_url = "://" in target or target.startswith("www.") or target.lower().startswith("mailto:")
                in_path = shutil.which(target) is not None
                
                # Strategy 1: Direct Run (if definitely runnable)
                if is_path or is_url or in_path:
                    try:
                        subprocess.run(f'start "" "{target}"', shell=True, check=True)
                        return ToolResult(status="success", stdout=f"Opened: {target}")
                    except Exception as e:
                         # Continue to other strategies if this failed specificially? 
                         # No, if 'start' failed on a valid path, it's likely a system issue or no handler.
                         pass

                # Strategy 2: Search Windows Start Menu Apps (Robust for UWP/Store Apps)
                try:
                    escaped = target.replace("'", "''").replace('"', '')
                    ps_script = (
                        f'$app = Get-StartApps | Where-Object {{ $_.Name -like "*{escaped}*" }} | Select-Object -First 1; '
                        'if ($app) { Start-Process ("shell:AppsFolder\\" + $app.AppID); Write-Output $app.Name } else { exit 1 }'
                    )
                    
                    res = subprocess.run(["powershell", "-Command", ps_script], check=True, capture_output=True, text=True)
                    app_name = res.stdout.strip()
                    return ToolResult(status="success", stdout=f"Launched App: {app_name}")
                except subprocess.CalledProcessError:
                     # Strategy 3: Last Resort - Try as Protocol
                     if ":" not in target and " " not in target:
                        try:
                             subprocess.run(f'start "" "{target}:"', shell=True, check=True)
                             return ToolResult(status="success", stdout=f"Opened URI: {target}:")
                        except: pass
                     
                     return ToolResult(status="error", stderr=f"Could not find app, file, or protocol named '{target}'. Try providing the full absolute path.")

            elif system == "Darwin":  # macOS
                subprocess.run(["open", target], check=True)
            else:  # Linux etc
                subprocess.run(["xdg-open", target], check=True)
                
            return ToolResult(
                status="success",
                stdout=f"Successfully signaled system to open: {target}",
            )
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)
