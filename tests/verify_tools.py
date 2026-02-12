
import logging
from src.alter.config import load_config
from src.alter.core.tools.web import make_web_research_tool, make_web_search_tool

logging.basicConfig(level=logging.INFO)

def test_research():
    cfg = load_config(None).config
    
    # Test Search
    print("Testing web.search...")
    search_tool = make_web_search_tool(cfg)
    res = search_tool.action({"query": "Clawdbot latest version"})
    print(f"Search Status: {res.status}")
    print(f"Search Output:\n{res.stdout[:500]}...\n")

    # Test Research
    print("Testing web.research...")
    research_tool = make_web_research_tool(cfg)
    res = research_tool.action({"query": "Clawdbot latest version", "max_pages": 1}) # 1 page for speed
    print(f"Research Status: {res.status}")
    print(f"Research Output:\n{res.stdout[:1000]}...\n")

if __name__ == "__main__":
    test_research()
