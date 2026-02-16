import logging
import httpx
from typing import Any, List
from urllib.parse import urlparse

# Try importing playwright; if not installed, we'll handle it gracefully in the tool.
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
except ImportError:
    sync_playwright = None
    PlaywrightTimeoutError = None

from .search_pipeline import SearchPipeline, SearchResult
from ...config import AlterConfig

logger = logging.getLogger(__name__)

class SurferAgent:
    """
    A persistent browser agent that can search and browse the web.
    Uses Playwright to render pages and extract content.
    Integrated with SearchPipeline for deep research.
    """
    
    def __init__(self, cfg: AlterConfig, headless: bool = True):
        self.cfg = cfg
        self.headless = headless
        self.pipeline = SearchPipeline(cfg)
        
    def _get_browser_args(self) -> dict[str, Any]:
        return {
            "headless": self.headless,
            "args": ["--disable-blink-features=AutomationControlled"] # Minor stealth
        }

    def search_searxng(
        self,
        query: str,
        base_url: str,
        max_results: int = 5,
        *,
        category: str | None = None,
        time_range: str | None = None,
    ) -> list[dict[str, str]]:
        """
        Legacy/Direct wrapper for SearXNG search.
        """
        # We can reuse the pipeline's logic or keep as is. 
        # For compatibility with existing tool in web.py, let's keep a simple wrapper
        # or just delegate to pipeline.search and convert back to dicts.
        results = self.pipeline.search(
            query,
            num_results=max_results,
            category=category,
            time_range=time_range,
        )
        return [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ]

    def search_google(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        """
        Performs a web search using the pipeline (SearXNG primary).
        Returns a list of results.
        """
        results = self.pipeline.search(query, num_results=max_results)
        return [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ]

    def browse(self, url: str) -> str:
        """
        Visits a URL and extracts its main text content.
        delegates to pipeline's fetch logic if possible, or keeps original implementation?
        Let's keep original implementation but maybe improve it.
        """
        if not sync_playwright:
             raise ImportError("Playwright is not installed.")

        text = ""
        with sync_playwright() as p:
            browser = p.chromium.launch(**self._get_browser_args())
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                # Helper to extract visible text
                text = page.evaluate("""() => {
                    return document.body.innerText;
                }""")
            except Exception as e:
                text = f"Error visiting {url}: {e}"
            finally:
                browser.close()
        
        return self._clean_text(text)

    def _clean_text(self, text: str) -> str:
        """Simple text cleanup."""
        if not text: 
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return "\n".join(lines)

    def surf(
        self,
        query: str,
        mode: str = "fast",
        max_results: int | None = None,
        llm_generate_fn=None,
        on_progress=None,
        prefer_rendered: bool = False,
        category: str | None = None,
        time_range: str | None = None,
        prefer_recent: bool = False,
        return_sources: bool = False,
    ):
        """
        Executes the full search pipeline: Search -> Fetch -> Rank -> Synthesize.
        """
        def _progress(msg: str):
            if on_progress:
                on_progress(msg)

        mode = (mode or "fast").strip().lower()
        if mode == "quick":
            mode = "fast"
        if mode not in {"fast", "deep"}:
            mode = "fast"

        # 1. Search
        if max_results is None:
            max_results = 18 if mode == "deep" else 5
        category = (category or "general").strip().lower()
        prefer_news = category == "news"
        if time_range:
            prefer_recent = True
        
        _progress(f"Searching for \"{query}\"...")
        results = self.pipeline.search(
            query,
            num_results=max_results,
            category=category,
            time_range=time_range,
            prefer_news=prefer_news,
        )
        
        if not results:
            return "No search results found to answer your query."
        
        _progress(f"Found {len(results)} results")

        # 2. Fetch
        _progress("Fetching pages...")
        if mode == "deep":
            prefer_rendered = True

        fetched_results = self.pipeline.fetch(
            results,
            mode=mode,
            on_progress=on_progress,
            prefer_rendered=prefer_rendered,
        )
        
        # 3. Rank
        _progress("Ranking results...")
        ranked_results = self.pipeline.rank(
            fetched_results,
            query,
            mode=mode,
            prefer_news=prefer_news,
            prefer_recent=prefer_recent,
        )

        # If fast mode ends up with too-thin evidence, escalate once to deep mode.
        usable = [r for r in ranked_results if (r.content or r.snippet).strip()]
        mode_for_synth = mode
        if mode == "fast" and len(usable) < 3:
            _progress("Fast pass was sparse, escalating to deep mode...")
            deep_results = self.pipeline.search(
                query,
                num_results=max(8, max_results),
                category=category,
                time_range=time_range,
                prefer_news=prefer_news,
            )
            deep_fetched = self.pipeline.fetch(
                deep_results,
                mode="deep",
                on_progress=on_progress,
                prefer_rendered=True,
            )
            ranked_results = self.pipeline.rank(
                deep_fetched,
                query,
                mode="deep",
                prefer_news=prefer_news,
                prefer_recent=prefer_recent,
            )
            mode_for_synth = "deep"
        
        # 4. Synthesize
        if llm_generate_fn:
            _progress("Synthesizing answer...")
            return self.pipeline.synthesize(
                query,
                ranked_results,
                llm_generate_fn,
                mode=mode_for_synth,
                prefer_news=prefer_news,
                prefer_recent=prefer_recent,
                return_sources=return_sources,
            )
        else:
            # If no LLM, just return a summary string
            out = []
            for r in ranked_results[:5]:
                summary = (r.content[:300] + "...") if r.content else r.snippet
                out.append(f"Title: {r.title}\nURL: {r.url}\nSummary: {summary}\n")
            return "\n".join(out)

