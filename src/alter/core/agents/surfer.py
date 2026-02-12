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

    def search_searxng(self, query: str, base_url: str, max_results: int = 5) -> list[dict[str, str]]:
        """
        Legacy/Direct wrapper for SearXNG search.
        """
        # We can reuse the pipeline's logic or keep as is. 
        # For compatibility with existing tool in web.py, let's keep a simple wrapper
        # or just delegate to pipeline.search and convert back to dicts.
        results = self.pipeline.search(query, num_results=max_results)
        return [
            {"title": r.title, "url": r.url, "snippet": r.snippet}
            for r in results
        ]

    def search_google(self, query: str, max_results: int = 5) -> list[dict[str, str]]:
        """
        Performs a web search using DuckDuckGo HTML (lighter/faster/less blocked than Google).
        Returns a list of results.
        """
        if not sync_playwright:
            raise ImportError("Playwright is not installed. Run `pip install playwright` and `playwright install`.")

        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(**self._get_browser_args())
            # Use a standard context
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            try:
                # Use html.duckduckgo.com for easier scraping (no heavy JS/anti-bot)
                url = f"https://html.duckduckgo.com/html/?q={query}"
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                
                # Check for "No results"
                if "No results found" in page.content():
                    return []

                # Wait for results container
                try:
                    page.wait_for_selector(".result", timeout=5000)
                except Exception:
                    pass
                
                # Extract results
                # Selectors for DDG HTML:
                # .result__title -> .result__a (link)
                # .result__snippet (text)
                elements = page.query_selector_all(".result")
                
                count = 0
                for el in elements:
                    if count >= max_results:
                        break
                    try:
                        title_el = el.query_selector(".result__title .result__a") or el.query_selector("a.result__a")
                        snippet_el = el.query_selector(".result__snippet")
                        
                        if title_el:
                            title = title_el.inner_text().strip()
                            url = title_el.get_attribute("href")
                            snippet = snippet_el.inner_text().strip() if snippet_el else ""
                            
                            if url:
                                results.append({
                                    "title": title,
                                    "url": url,
                                    "snippet": snippet
                                })
                                count += 1
                    except Exception:
                        continue
                        
            except Exception as e:
                logger.error(f"Surfing error: {e}")
                results.append({"title": "Error", "url": "", "snippet": str(e)})
            finally:
                browser.close()
                
        return results

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

    def surf(self, query: str, mode: str = "fast", max_results: int | None = None, llm_generate_fn = None, on_progress = None) -> str:
        """
        Executes the full search pipeline: Search -> Fetch -> Rank -> Synthesize.
        """
        def _progress(msg: str):
            if on_progress:
                on_progress(msg)

        # 1. Search
        if max_results is None:
            max_results = 10 if mode == "deep" else 5
        
        _progress(f"Searching for \"{query}\"...")
        results = self.pipeline.search(query, num_results=max_results)
        
        if not results:
            return "No search results found to answer your query."
        
        _progress(f"Found {len(results)} results")

        # 2. Fetch
        _progress("Fetching pages...")
        fetched_results = self.pipeline.fetch(results, mode=mode, on_progress=on_progress)
        
        # 3. Rank
        _progress("Ranking results...")
        ranked_results = self.pipeline.rank(fetched_results, query)
        
        # 4. Synthesize
        if llm_generate_fn:
            _progress("Synthesizing answer...")
            return self.pipeline.synthesize(query, ranked_results, llm_generate_fn)
        else:
            # If no LLM, just return a summary string
            out = []
            for r in ranked_results[:5]:
                out.append(f"Title: {r.title}\nURL: {r.url}\nSummary: {r.snippet}\n")
            return "\n".join(out)

