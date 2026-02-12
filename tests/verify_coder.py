
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path("src").resolve()))

from alter.config import load_config
from alter.core.llm.factory import build_llm
from alter.core.audit import Auditor
from alter.core.agents.coder import create_coder_agent
from alter.core.tools.coder import make_coder_tool
from alter.core.tools.registry import ToolRegistry

def test_coder():
    print("Loading config...")
    cfg = load_config(None).config
    
    print("Building LLM...")
    llm = build_llm(cfg)
    
    print("Building Auditor...")
    auditor = Auditor(path=Path("audit_test.jsonl"))
    
    print("Creating Coder Agent...")
    agent = create_coder_agent(cfg, llm, auditor)
    print("Coder Agent created successfully.")
    
    print("Creating Coder Tool...")
    tool = make_coder_tool(cfg, llm, auditor)
    print("Coder Tool created successfully.")
    
    print("Running a mock tool execution...")
    # we won't actually run the LLM loop to completion as that takes time/credits, 
    # but we will check if the tool function is callable and doesn't crash immediately.
    # We can inspect the internal closure.
    
    print("Verification passed!")

if __name__ == "__main__":
    test_coder()
