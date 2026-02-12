from __future__ import annotations

import json
from typing import Any

from ...config import AlterConfig
from ..agent import AgentSession, FinalResponse
from ..agents.coder import create_coder_agent
from ..audit import Auditor
from ..llm.base import Llm
from .base import Tool, ToolResult, ToolSpec


def make_coder_tool(cfg: AlterConfig, llm: Llm, auditor: Auditor) -> Tool:
    # We can cache the agent if we want persistence, but for now let's rebuild it (lightweight).
    # actually, keeping it stateless is safer for "tasks".
    
    def run_coder_task(task: str, files: list[str] | None = None) -> ToolResult:
        agent = create_coder_agent(cfg, llm, auditor)
        # Create a new session for this task
        session = agent.new_session(owner="coder_tool")
        
        # Construct the initial prompt from the inputs
        prompt = f"Task: {task}"
        if files:
            prompt += f"\nRelevant Files: {', '.join(files)}"
        
        # Run the loop
        # We need a way to run until completion. AgentSession.run_turn does one turn (User -> Agent -> Tool -> Agent -> Final).
        # But here we want the "User" (Main Agent) to say "Do this", and the Coder Agent to loop autonomously until it says "Final".
        # AgentSession.run_turn(user_message=...) returns AgentResult.
        # If AgentResult is FinalResponse, we are done.
        # If AgentResult is ToolRequest, the session executes it and loops internally up to `max_steps`.
        # AgentSession.run_turn handles the loop!
        
        try:
            result = session.run_turn(user_message=prompt, max_steps=15) # Give it plenty of steps
            
            if isinstance(result, FinalResponse):
                return ToolResult(status="success", stdout=result.content)
            else:
                # Should not happen if run_turn handles the loop, unless it hit max_steps
                return ToolResult(status="error", stderr="Coder Agent timed out or did not return a final response.")
                
        except Exception as e:
            return ToolResult(status="error", stderr=f"Coder Agent failed: {e}")

    return Tool(
        spec=ToolSpec(
            id="coder.task",
            name="Coder Agent Task",
            description="Delegate a complex coding or exploration task to the specialized Coder Agent.",
            inputs_schema={
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "Detailed instructions for the coding task."
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of relevant file paths to focus on."
                    }
                },
                "required": ["task"]
            },
            confirm=True, # Always confirm delegation to a powerful agent
        ),
        action=lambda inputs: run_coder_task(inputs["task"], inputs.get("files")),
    )
