from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_launcher_tool(require_confirmation: bool = True) -> Tool:
    spec = ToolSpec(
        id="launcher.open",
        name="Launch App/File",
        description=(
            "Launch an application or open a file using the system's default handler. "
            "Use this to open executables (like 'code', 'calc', 'notepad') or files/folders. "
            "Returns immediately."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "The path to the file/folder or the name of the executable (e.g., 'code', '.', 'C:/Users')."
                },
            },
            "required": ["target"],
            "additionalProperties": False,
        },
        confirm=require_confirmation,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        target = inputs["target"]
        system = platform.system()

        try:
            if system == "Windows":
                import shutil
                from pathlib import Path

                # Helper: Check if runnable
                is_path = os.path.exists(target)
                is_url = "://" in target or target.startswith("www.") or target.lower().startswith("mailto:")
                in_path = shutil.which(target) is not None
                
                # Strategy 1: Direct Run (if definitely runnable)
                if is_path or is_url or in_path:
                    try:
                        subprocess.run(f'start "" "{target}"', shell=True, check=True)
                        return ToolResult(status="success", stdout=f"Opened: {target}")
                    except Exception:
                        pass # Fallthrough if failed (unlikely if checks passed, but safest)

                # Strategy 2: Protocol (e.g. "whatsapp:" or "ms-settings:")
                if ":" not in target and " " not in target:
                     try:
                        pass
                     except: pass

                # Strategy 3: Search Windows Start Menu Apps (Robust for UWP/Store Apps)
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
                     # Strategy 4: Last Resort - Try as Protocol
                     if ":" not in target and " " not in target:
                        try:
                             subprocess.run(f'start "" "{target}:"', shell=True, check=True)
                             return ToolResult(status="success", stdout=f"Opened URI: {target}:")
                        except: pass
                     
                     return ToolResult(status="error", stderr=f"Could not find app or file named '{target}'. Try the specific path.")

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
