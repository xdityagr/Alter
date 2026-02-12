
from __future__ import annotations

from ...config import AlterConfig
from .fs import make_fs_list_tool, make_fs_read_tool
from .git import make_git_diff_tool, make_git_status_tool
from .rename import make_fs_rename_tool
from .registry import ToolRegistry
from .search import make_text_search_tool
from .shell import ShellPolicy, make_shell_tool
from .web import make_web_surf_tool
from .system import make_system_info_tool, make_system_snapshot_tool
from .write import make_fs_write_tool
from .launcher import make_launcher_tool
from .clipboard import make_clipboard_read_tool, make_clipboard_write_tool
from .time import make_time_now_tool
from .coder import make_coder_tool
from ..llm.base import Llm
from ..audit import Auditor


def build_default_registry(cfg: AlterConfig, llm: Llm, auditor: Auditor) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(make_system_info_tool())
    reg.register(make_system_snapshot_tool())
    reg.register(make_time_now_tool())
    reg.register(make_fs_read_tool())
    reg.register(make_fs_list_tool())
    reg.register(make_fs_write_tool(allowed_roots=cfg.security.allowed_write_roots, require_confirmation=True))
    reg.register(make_fs_rename_tool(allowed_roots=cfg.security.allowed_write_roots, require_confirmation=True))
    reg.register(make_text_search_tool())
    reg.register(make_git_status_tool())
    reg.register(make_git_diff_tool())
    reg.register(
        make_shell_tool(
            ShellPolicy(
                # Power User: Allow common shell commands by default.
                allowed_programs=set(
                    cfg.security.allowed_commands
                    + [
                        "cmd",
                        "powershell",
                        "pwsh",
                        "dir",
                        "echo",
                        "where",
                        "whoami",
                        "ipconfig",
                        "ping",
                        "type",
                        "net",
                        "systeminfo",
                        "code",  # VS Code
                        "notepad",
                        "calc",
                    ]
                ),
                require_confirmation=cfg.security.require_confirmation and not cfg.security.auto_confirm_shell,
            )
        )
    )
    reg.register(make_web_surf_tool(cfg, llm))
    reg.register(make_clipboard_read_tool())
    reg.register(make_clipboard_write_tool())
    reg.register(make_launcher_tool(require_confirmation=True))
    reg.register(make_coder_tool(cfg, llm, auditor))
    return reg
