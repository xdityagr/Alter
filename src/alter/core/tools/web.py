from __future__ import annotations

from typing import Any
from ...config import AlterConfig
from ..llm.base import Llm
from .base import Tool, ToolResult, ToolSpec
from ..agents.surfer import SurferAgent

def make_web_search_tool(cfg: AlterConfig) -> Tool:
    spec = ToolSpec(
        id="web.search",
        name="Web Search",
        description="Search the web using a real browser (Google).",
        inputs_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "max_results": {"type": "integer", "default": 5, "maximum": 10},
            },
            "required": ["query"],
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any], on_progress=None) -> ToolResult:
        query = inputs["query"]
        max_results = int(inputs.get("max_results", 5))
        
        try:
            if on_progress:
                on_progress(f"Searching for \"{query}\"...")
            agent = SurferAgent(cfg, headless=cfg.web.rendered_headless)
            
            # Use pipeline search
            results = agent.search_searxng(query, "", max_results=max_results)
            import logging
            logging.getLogger(__name__).debug(f"Search '{query}' returned {len(results)} results.")

            if on_progress:
                on_progress(f"Found {len(results)} results")
            
            if not results:
                return ToolResult(status="ok", stdout="No results found.")
            
            # Check for error object from SurferAgent
            if len(results) == 1 and results[0].get("title") == "Error":
                 return ToolResult(status="error", stderr=f"Search Engine Error: {results[0].get('snippet')}")

            lines = []
            for i, r in enumerate(results, 1):
                lines.append(f"{i}. [{r['title']}]({r['url']})\n   {r['snippet']}\n")
            
            return ToolResult(status="ok", stdout="\n".join(lines).strip())
            
        except ImportError:
             return ToolResult(status="error", stderr="Playwright is not installed. Please run `pip install playwright` and `playwright install`.")
        except Exception as e:
            return ToolResult(status="error", stderr=f"Search failed: {e}")

    return Tool(spec=spec, action=action)


def make_web_surf_tool(cfg: AlterConfig, llm: Llm) -> Tool:
    spec = ToolSpec(
        id="web.surf",
        name="Web Surf (Deep Research)",
        description="Search the web, fetch pages, and synthesize an answer. Use mode='fast' for simple factual queries (weather, stock prices, quick lookups). Use mode='deep' for complex research requiring multiple sources.",
        inputs_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or research topic"},
                "mode": {"type": "string", "enum": ["fast", "deep"], "default": "fast", "description": "Use 'fast' for simple factual queries (weather, prices, scores, quick lookups). Use 'deep' for complex research needing multiple sources."},
            },
            "required": ["query"],
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any], on_progress=None) -> ToolResult:
        query = str(inputs["query"]).strip()
        mode = str(inputs.get("mode", "deep"))

        try:
            agent = SurferAgent(cfg, headless=cfg.web.rendered_headless)
            
            # Define generation function wrapper
            def generate_fn(system_prompt: str, user_prompt: str) -> str:
                return llm.generate(system_prompt=system_prompt, user_prompt=user_prompt)
            
            # Execute surf loop
            result = agent.surf(query, mode=mode, llm_generate_fn=generate_fn, on_progress=on_progress)
            return ToolResult(status="ok", stdout=result)

        except ImportError:
             return ToolResult(status="error", stderr="Playwright or other dependencies not installed.")
        except Exception as e:
            return ToolResult(status="error", stderr=f"Surfing failed: {e}")

    return Tool(spec=spec, action=action)



def make_web_visit_tool(cfg: AlterConfig) -> Tool:

    # Deprecated/Alias for web.visit_rendered but included for compatibility or simple requests
    # We will just redirect to our SurferAgent.browse for consistency
    spec = ToolSpec(
        id="web.visit",
        name="Visit URL",
        description="Visit a webpage and extract its text content.",
        inputs_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to visit"},
            },
            "required": ["url"],
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any], on_progress=None) -> ToolResult:
        url = inputs["url"]
        try:
            if on_progress:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc or url
                on_progress(f"Visiting {domain}...")
            agent = SurferAgent(cfg, headless=True)
            content = agent.browse(url)
            if on_progress:
                on_progress("Extracting content...")

            return ToolResult(status="ok", stdout=content[:8000])
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)


def make_web_visit_rendered_tool(cfg: AlterConfig) -> Tool:
    spec = ToolSpec(
        id="web.visit_rendered",
        name="Visit URL (Rendered)",
        description="Visit a webpage in a browser (JS-rendered) and extract text.",
        inputs_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to visit"},
            },
            "required": ["url"],
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any], on_progress=None) -> ToolResult:
        url = str(inputs["url"]).strip()
        try:
            if on_progress:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc or url
                on_progress(f"Rendering {domain}...")
            agent = SurferAgent(cfg, headless=cfg.web.rendered_headless)
            content = agent.browse(url)
            if on_progress:
                on_progress("Extracting content...")

            return ToolResult(status="ok", stdout=content[:8000])
        except Exception as e:
            return ToolResult(status="error", stderr=str(e))

    return Tool(spec=spec, action=action)
