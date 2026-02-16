from __future__ import annotations

from typing import Any
from ...config import AlterConfig
from ..llm.base import Llm
from .base import Tool, ToolResult, ToolSpec
from ..agents.surfer import SurferAgent

def _should_refine_query(query: str) -> bool:
    q = (query or "").strip()
    if len(q) <= 50:
        return False
    if len(q.split()) <= 8:
        return False
    return True


def _refine_query(llm: Llm | None, query: str) -> str:
    q = (query or "").strip()
    if not _should_refine_query(q) or llm is None:
        return q
    prompt = (
        "Rewrite the user's request into a short web search query (3-8 words). "
        "Preserve named entities and key terms. Do NOT add facts. "
        "If the user asks for latest/new, include 'latest' or 'new' in the query. "
        "Return ONLY the rewritten query string, nothing else.\n\n"
        f"User request: {q}"
    )
    try:
        refined = (llm.generate(system_prompt="You rewrite user requests into concise search queries.", user_prompt=prompt) or "").strip()
    except Exception:
        return q
    if not refined or len(refined) < 3:
        return q
    # Safety: avoid overly long outputs
    if len(refined) > 120:
        return q
    return refined


def make_web_search_tool(cfg: AlterConfig) -> Tool:
    spec = ToolSpec(
        id="web.search",
        name="Web Search",
        description="Search the web using SearXNG (and fallbacks).",
        inputs_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "max_results": {"type": "integer", "default": 5, "maximum": 10},
                "category": {"type": "string", "description": "Optional SearXNG category (e.g., news, videos, general)."},
                "time_range": {"type": "string", "enum": ["day", "week", "month", "year"], "description": "Limit results to a recent time range."},
            },
            "required": ["query"],
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any], on_progress=None) -> ToolResult:
        query = inputs["query"]
        max_results = int(inputs.get("max_results", 5))
        category = inputs.get("category")
        time_range = inputs.get("time_range")
        
        try:
            if on_progress:
                on_progress(f"Searching for \"{query}\"...")
            agent = SurferAgent(cfg, headless=cfg.web.rendered_headless)
            
            # Use pipeline search
            results = agent.search_searxng(
                query,
                "",
                max_results=max_results,
                category=category,
                time_range=time_range,
            )
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
        description="Search the web, fetch pages, rank sources, and synthesize an answer. Use mode='fast' for quick lookups and mode='deep' for multi-source analysis. Set time_range to request recency; no automatic time filtering is applied.",
        inputs_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query or research topic"},
                "mode": {"type": "string", "enum": ["fast", "deep", "quick"], "default": "fast", "description": "fast/quick = latency-first. deep = more sources + heavier fetch."},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 20, "description": "Max result pages/sources to process."},
                "rendered": {"type": "boolean", "default": False, "description": "Prefer JS-rendered extraction for harder sites (slower)."},
                "category": {"type": "string", "description": "Optional SearXNG category (e.g., news, videos, general)."},
                "time_range": {"type": "string", "enum": ["day", "week", "month", "year"], "description": "Limit results to a recent time range."},
                "prefer_recent": {"type": "boolean", "default": False, "description": "Boost recent sources when timestamps are available."},
            },
            "required": ["query"],
        },
        confirm=False,
    )

    def action(inputs: dict[str, Any], on_progress=None) -> ToolResult:
        query = str(inputs["query"]).strip()
        mode = str(inputs.get("mode", "fast")).strip().lower()
        if mode == "quick":
            mode = "fast"
        if mode not in {"fast", "deep"}:
            mode = "fast"
        max_pages = inputs.get("max_pages")
        try:
            max_pages = int(max_pages) if max_pages is not None else None
        except Exception:
            max_pages = None
        rendered = bool(inputs.get("rendered", False))
        category = inputs.get("category")
        time_range = inputs.get("time_range")
        prefer_recent = bool(inputs.get("prefer_recent", False))

        try:
            refined_query = _refine_query(llm, query)
            if refined_query != query:
                if on_progress:
                    on_progress(f"Refined query to \"{refined_query}\"")
                query = refined_query
            agent = SurferAgent(cfg, headless=cfg.web.rendered_headless)
            
            # Define generation function wrapper
            def generate_fn(system_prompt: str, user_prompt: str) -> str:
                return llm.generate(system_prompt=system_prompt, user_prompt=user_prompt)
            
            # Execute surf loop
            result = agent.surf(
                query,
                mode=mode,
                max_results=max_pages,
                llm_generate_fn=generate_fn,
                on_progress=on_progress,
                prefer_rendered=rendered,
                category=category,
                time_range=time_range,
                prefer_recent=prefer_recent,
                return_sources=True,
            )
            if isinstance(result, tuple) and len(result) == 2:
                answer, sources = result
                artifacts = {
                    "query": query,
                    "mode": mode,
                    "category": category,
                    "time_range": time_range,
                    "prefer_recent": prefer_recent,
                    "sources": [
                        {
                            "id": r.source_id,
                            "title": r.title,
                            "url": r.url,
                            "snippet": r.snippet,
                            "has_content": bool((r.content or "").strip()),
                            "published_ts": r.published_ts,
                        }
                        for r in sources
                    ],
                }
                return ToolResult(status="ok", stdout=answer, artifacts=artifacts)
            return ToolResult(status="ok", stdout=str(result))

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
