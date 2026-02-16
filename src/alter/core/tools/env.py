from __future__ import annotations

import os
from typing import Any

from .base import Tool, ToolResult, ToolSpec


def make_env_get_tool() -> Tool:
    spec = ToolSpec(
        id="env.get",
        name="Get Environment Variable",
        description=(
            "Read one or more environment variables. Use this to check PATH, CONDA_PREFIX, "
            "VIRTUAL_ENV, JAVA_HOME, etc. instead of guessing."
        ),
        inputs_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Name of the environment variable to read. If omitted, returns all variables.",
                },
            },
            "additionalProperties": False,
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any]) -> ToolResult:
        var_name = str(inputs.get("name", "")).strip()

        try:
            if var_name:
                value = os.environ.get(var_name)
                if value is None:
                    return ToolResult(
                        status="ok",
                        stdout=f"Environment variable '{var_name}' is not set.",
                        artifacts={"name": var_name, "exists": False},
                    )
                # For PATH-like variables, format nicely
                if var_name.upper() in ("PATH", "PATHEXT", "PSMODULEPATH") and os.pathsep in value:
                    formatted = "\n".join(value.split(os.pathsep))
                    return ToolResult(
                        status="ok",
                        stdout=f"{var_name}:\n{formatted}",
                        artifacts={"name": var_name, "exists": True, "entries": len(value.split(os.pathsep))},
                    )
                return ToolResult(
                    status="ok",
                    stdout=f"{var_name}={value}",
                    artifacts={"name": var_name, "exists": True},
                )
            else:
                # Return all variables (sorted, truncated for safety)
                env_vars = sorted(os.environ.items(), key=lambda x: x[0].lower())
                lines = []
                for k, v in env_vars[:80]:
                    # Truncate very long values
                    display_v = v if len(v) <= 200 else v[:200] + "..."
                    lines.append(f"{k}={display_v}")
                output = "\n".join(lines)
                return ToolResult(
                    status="ok",
                    stdout=output,
                    artifacts={"total_vars": len(env_vars), "shown": min(80, len(env_vars))},
                )

        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)
