from __future__ import annotations

import logging
import httpx
import trafilatura
import concurrent.futures
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from ...config import AlterConfig
from datetime import datetime

logger = logging.getLogger(__name__)

# Try importing playwright for fallback
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

# Try importing sentence_transformers for ranking
try:
    from sentence_transformers import SentenceTransformer, util
    _RANKER_MODEL = None
    
    def get_ranker():
        global _RANKER_MODEL
        if _RANKER_MODEL is None:
            # Load a lightweight model
            _RANKER_MODEL = SentenceTransformer('all-MiniLM-L6-v2')
        return _RANKER_MODEL
except ImportError:
    get_ranker = None
    logger.warning("sentence-transformers not installed. Semantic ranking will be disabled.")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    content: str = ""
    score: float = 0.0
    source_id: int = 0

class SearchPipeline:
    def __init__(self, cfg: AlterConfig):
        self.cfg = cfg
        self.searxng_url = cfg.web.searxng_base_url
        if not self.searxng_url:
            logger.warning("SearXNG URL not configured.")

    def search(self, query: str, num_results: int = 5) -> List[SearchResult]:
        """
        Searches SearXNG or Google/DDG fallback.
        """
        results = []
        if self.searxng_url:
             try:
                params = {
                    "q": query,
                    "format": "json",
                    "categories": "general",
                    "language": "en-US",
                }
                # Remove trailing slash
                base = self.searxng_url.rstrip("/")
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(f"{base}/search", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    
                    raw_results = data.get("results", [])
                    for i, r in enumerate(raw_results[:num_results]):
                         results.append(SearchResult(
                             title=r.get("title", ""),
                             url=r.get("url", ""),
                             snippet=r.get("content", ""),
                             source_id=i+1
                         ))
             except Exception as e:
                 logger.error(f"SearXNG search failed: {e}")
        
        # Fallback if no results or no SearXNG (simulated for now by just returning empty if failed)
        return results

    def fetch(self, results: List[SearchResult], mode: str = "fast", on_progress=None) -> List[SearchResult]:
        """
        Fetches content for the given results in parallel.
        """
        # Dedup by URL before fetching
        unique_results = []
        seen_urls = set()
        for r in results:
            if r.url not in seen_urls:
                unique_results.append(r)
                seen_urls.add(r.url)
        
        fetched_results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_result = {
                executor.submit(self._fetch_single, r, mode): r 
                for r in unique_results
            }
            
            for future in concurrent.futures.as_completed(future_to_result):
                r = future_to_result[future]
                try:
                    content = future.result()
                    if content:
                        r.content = content
                        fetched_results.append(r)
                        if on_progress:
                            # Extract domain for a clean display
                            from urllib.parse import urlparse
                            domain = urlparse(r.url).netloc or r.url
                            on_progress(f"Fetched {domain}")
                except Exception as e:
                    logger.error(f"Error fetching {r.url}: {e}")
                    
        return fetched_results

    def _fetch_single(self, result: SearchResult, mode: str) -> str:
        """
        Fetches a single URL using Trafilatura, optionally falling back to Playwright.
        """
        # Common headers to look like a real browser
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        # 1. Try Trafilatura (fastest) - with custom config/headers if possible, 
        # but trafilatura.fetch_url is simple. We can try requests first or let it handle.
        # However, trafilatura doesn't easily accept custom headers in `fetch_url` without config.
        # So we download with httpx first to control headers/timeout, then pass to trafilatura.
        try:
            # Short timeout for fast mode to avoid hanging on slow/blocked sites
            timeout = 5.0 if mode == "fast" else 10.0
            
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                resp = client.get(result.url)
                resp.raise_for_status()
                # Extract main text
                text = trafilatura.extract(resp.text)
                if text:
                    return text
        except Exception:
            # If http fetch fails, we might fall back to playwright below if deep mode
            pass
        
        # 2. If 'deep' mode and Playwright is available, try it
        # Also fall back if fast mode failed but we have playwright and it's indispensable? 
        # No, keep fast mode fast. Only deep mode gets the heavy browser.
        if mode == "deep" and sync_playwright:
             try:
                 with sync_playwright() as p:
                    # random user agent?
                    browser = p.chromium.launch(headless=self.cfg.web.rendered_headless)
                    # context = browser.new_context(user_agent=headers["User-Agent"])
                    page = browser.new_page(user_agent=headers["User-Agent"])
                    
                    # shorter timeout for fallback to avoid hanging too long
                    try:
                        page.goto(result.url, wait_until="domcontentloaded", timeout=15000)
                    except Exception:
                        # If timeout, just try to get what we have
                        pass
                        
                    content = page.evaluate("document.body.innerText")
                    browser.close()
                    # Clean it a bit
                    return trafilatura.extract(content) or content
             except Exception as e:
                 logger.warning(f"Playwright fallback failed for {result.url}: {e}")
        
        return ""

    def rank(self, results: List[SearchResult], query: str) -> List[SearchResult]:
        """
        Ranks results by semantic similarity to the query.
        """
        if not results:
            return []
            
        if not get_ranker:
            return results # Return as-is if no ranker

        model = get_ranker()
        
        # Compute embeddings
        query_emb = model.encode(query, convert_to_tensor=True)
        
        # Prepare docs: Title + Snippet + (Head of content)
        docs = []
        for r in results:
            # Mix title and snippet and first 500 chars of content
            text = f"{r.title} {r.snippet} {r.content[:500]}"
            docs.append(text)
            
        doc_embs = model.encode(docs, convert_to_tensor=True)
        
        # Compute scores
        # cosine_scores is a list of tensors
        scores = util.cos_sim(query_emb, doc_embs)[0]
        
        # Assign scores
        for i, r in enumerate(results):
            r.score = float(scores[i])
            
        # Sort by score desc
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def synthesize(self, query: str, results: List[SearchResult], llm_generate_fn) -> str:
        """
        Synthesizes a final answer using the LLM.
        """
        if not results:
            return "No results found to answer your query."
            
        # Context construction - use top 10 results
        context = []
        # Use a map for post-processing links later
        source_map = {}
        
        for r in results[:10]: # Top 10
            # Use content if available, otherwise snippet. 
            # Ideally use both: snippet is the search engine's view, content is the page's view.
            text = r.content[:2000] if r.content else r.snippet
            context.append(f"Source [{r.source_id}]: {r.title} ({r.url})\nSnippet: {r.snippet}\nContent: {text}\n")
            source_map[str(r.source_id)] = r.url
            
        context_str = "\n---\n".join(context)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        prompt = f"""You are a helpful research assistant. Answer the user's query based strictly on the provided search results.
        
User's Local Date/Time: {current_time}
Query: {query}

Search Results:
{context_str}

Instructions:
- Synthesize the information into a coherent answer.
- Cite sources using [Source ID].
- If the results don't contain the answer, say "I couldn't find information about that."
- Be concise but comprehensive.
- IMPORTANT: If search results have conflicting data, prefer the most recent or authoritative source.
- Do NOT hallucinate. 
- NOTE: The "User's Local Date/Time" is your reference. If the user asks for time in another city, use search results to find the timezone offset and calculate it if necessary, or report the time found in the results.
"""
        raw_answer = llm_generate_fn(system_prompt="You are a research assistant.", user_prompt=prompt)
        
        # Post-process to inject links: [Source 1] -> [[Source 1](url)]
        # We use a regex to find [Source ID] and replace it with a markdown link.
        import re
        
        def replace_source(match):
            sid = match.group(1)
            url = source_map.get(sid)
            if url:
                return f"[[Source {sid}]({url})]"
            return match.group(0) # No change if ID not found
            
        final_answer = re.sub(r'\[Source (\d+)\]', replace_source, raw_answer)
        return final_answer
