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
        target = inputs["target"]
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
