from __future__ import annotations

from typing import Any

from ...config import AlterConfig
from ..agent import Agent
from ..audit import Auditor
from ..llm.base import Llm
from ..tools.fs import make_fs_list_tool, make_fs_read_tool
from ..tools.write import make_fs_write_tool
from ..tools.git import make_git_diff_tool, make_git_status_tool
from ..tools.registry import ToolRegistry
from ..tools.rename import make_fs_rename_tool
from ..tools.search import make_text_search_tool
from ..tools.shell import ShellPolicy, make_shell_tool

CODER_SYSTEM_PROMPT = """You are the Coder Agent, an expert software engineering subsystem.
Your mission is to EXECUTE coding tasks with precision, safety, and autonomy.

ROLE & CONTEXT:
- You are triggered by the Main Agent to handle multi-step coding, refactoring, or exploration tasks.
- You operate in the user's local environment.
- You do NOT interact with the human user directly. Your "user" is the Main Agent.
- Your output {"type": "final", "content": "..."} is returned to the Main Agent as the result of the tool call.

GUIDELINES:
1. EXPLORE FIRST: explicitly list files or read content before editing. Do not guess paths.
2. VERIFY: After writing a file, optionally read it back or run a syntax check if simple.
3. INCREMENTAL: If a task is huge, break it down.
4. ERROR RECOVERY: If a tool fails (e.g. file not found), attempt to fix the path or create the file. Do not immediately fail.
5. NO CHATTER: Do not include "I will now do X" in the final response unless it's the summary of work done. The final response should be a clean summary of changes.

Response Format:
Standard JSON tool usage as defined in the main system prompt.
"""


def build_coder_tools(cfg: AlterConfig) -> ToolRegistry:
    """
    Constructs a tool registry specifically for the Coder Agent.
    Includes: FS (Read/Write/List/Rename), Git, Shell, Text Search.
    Excludes: Web functionalities, System snapshot, Launcher.
    """
    reg = ToolRegistry()
    
    # Filesystem - core capability
    allowed = cfg.security.allowed_write_roots
    reg.register(make_fs_read_tool())
    reg.register(make_fs_list_tool())
    # Coder agent is explicitly authorized to write/rename without per-action human confirmation *if* the main agent delegated it.
    # However, for safety, we might normally want confirmation. 
    # But since this is a "sub-agent" running inside a tool call that the user approved (assuming @coder.task is confirmed),
    # we can set require_confirmation=False for the sub-agent's tools to allow autonomy.
    # PROCEED WITH CAUTION: This makes the Coder Agent powerful.
    reg.register(make_fs_write_tool(allowed_roots=allowed, require_confirmation=False))
    reg.register(make_fs_rename_tool(allowed_roots=allowed, require_confirmation=False))
    
    # Search
    reg.register(make_text_search_tool())
    
    # Git
    reg.register(make_git_status_tool())
    reg.register(make_git_diff_tool())
    
    # Shell - Restricted but useful for running tests/checks
    # We use the same allowed commands as the main agent
    reg.register(
        make_shell_tool(
            ShellPolicy(
                allowed_programs=set(cfg.security.allowed_commands + ["python", "pytest", "npm", "node", "git", "ls", "dir", "echo", "cat", "type"]),
                require_confirmation=False, # Autonomous shell usage for approved commands
            )
        )
    )
    
    return reg


def create_coder_agent(
    cfg: AlterConfig,
    llm: Llm,
    auditor: Auditor,
    memory_enabled: bool = False, # Coder agent usually doesn't need long-term memory, just context
) -> Agent:
    tools = build_coder_tools(cfg)
    
    return Agent(
        llm=llm,
        tools=tools,
        auditor=auditor,
        thinking_mode=cfg.llm.thinking_mode,
        memory_enabled=False, # Stateless for now, simplifies things
        system_prompt=CODER_SYSTEM_PROMPT,
    )
