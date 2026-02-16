from __future__ import annotations

import concurrent.futures
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import List
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, unquote, urlparse

import httpx
try:
    import trafilatura
except Exception:
    trafilatura = None

from ...config import AlterConfig

logger = logging.getLogger(__name__)

# Optional HTML parser fallback
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

# Optional rendered browsing fallback
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

# Optional semantic ranker
try:
    from sentence_transformers import SentenceTransformer, util

    _RANKER_MODEL = None

    def get_ranker():
        global _RANKER_MODEL
        if _RANKER_MODEL is None:
            _RANKER_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        return _RANKER_MODEL
except ImportError:
    _RANKER_MODEL = None
    get_ranker = None
    logger.warning("sentence-transformers not installed. Semantic ranking disabled.")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    content: str = ""
    score: float = 0.0
    source_id: int = 0
    published_ts: float | None = None


class SearchPipeline:
    _USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, cfg: AlterConfig):
        self.cfg = cfg
        self.searxng_url = (cfg.web.searxng_base_url or "").strip() or None
        if not self.searxng_url:
            logger.warning("SearXNG URL not configured.")
        self._agg_domains = {
            "msn.com",
            "news.google.com",
            "news.yahoo.com",
            "finance.yahoo.com",
            "newsnow.co.uk",
            "newsbreak.com",
            "feedproxy.google.com",
        }
        self._preferred_news_domains = {
            "reuters.com",
            "apnews.com",
            "bbc.com",
            "bloomberg.com",
            "thehindu.com",
            "timesofindia.indiatimes.com",
            "indianexpress.com",
            "livemint.com",
            "economictimes.indiatimes.com",
        }

    def search(
        self,
        query: str,
        num_results: int = 5,
        *,
        category: str | None = None,
        time_range: str | None = None,
        prefer_news: bool | None = None,
    ) -> List[SearchResult]:
        """
        Search stack:
        1) SearXNG (primary)
        2) Bing web HTML parse
        3) Bing News RSS (for explicit news queries)
        """
        query = (query or "").strip()
        if not query:
            return []

        target = max(1, min(int(num_results), 20))
        category = (category or "general").strip().lower()
        if category == "news":
            prefer_news = True
        elif prefer_news is None:
            prefer_news = False
        if time_range:
            time_range = str(time_range).strip().lower()
            if time_range not in {"day", "week", "month", "year"}:
                time_range = None
        combined: list[SearchResult] = []

        searx_limit = target
        if prefer_news:
            searx_limit = max(3, target // 2)

        if self.searxng_url:
            combined.extend(
                self._search_searxng(
                    query,
                    target=searx_limit,
                    prefer_news=prefer_news,
                    category=category,
                    time_range=time_range,
                )
            )

        # For news queries, always mix in alternate providers to improve source diversity.
        if prefer_news:
            combined.extend(self._search_bing_news_rss(query, target=target * 2))
            combined.extend(self._search_bing_html(query, target=target * 2))
        else:
            if len(combined) < target:
                combined.extend(self._search_bing_html(query, target=target * 2))

        deduped = self._dedupe_results(combined, limit=target)
        for i, r in enumerate(deduped, 1):
            r.source_id = i
        return deduped

    def _search_searxng(
        self,
        query: str,
        *,
        target: int,
        prefer_news: bool,
        category: str,
        time_range: str | None,
    ) -> list[SearchResult]:
        out: list[SearchResult] = []
        base = self.searxng_url.rstrip("/")
        params = {
            "q": query,
            "format": "json",
            "language": "en-US",
            "categories": category or ("news" if prefer_news else "general"),
        }
        if time_range:
            params["time_range"] = time_range

        try:
            with httpx.Client(
                timeout=httpx.Timeout(8.0),
                follow_redirects=True,
                headers={"User-Agent": self._USER_AGENT},
            ) as client:
                resp = client.get(f"{base}/search", params=params)
                resp.raise_for_status()
                data = resp.json()

            for r in data.get("results", []):
                title = str(r.get("title") or "").strip()
                url = self._clean_url(str(r.get("url") or "").strip())
                snippet = str(r.get("content") or "").strip()
                pub = r.get("publishedDate") or r.get("published_date") or r.get("published")
                pub_ts = self._parse_time(pub)
                if title and url:
                    out.append(SearchResult(title=title, url=url, snippet=snippet, published_ts=pub_ts))
                if len(out) >= target:
                    break
        except Exception as e:
            logger.warning("SearXNG search failed: %s", e)
        return out

    def _search_duckduckgo_html(self, query: str, *, target: int) -> list[SearchResult]:
        out: list[SearchResult] = []
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10.0),
                follow_redirects=True,
                headers={"User-Agent": self._USER_AGENT},
            ) as client:
                resp = client.get("https://html.duckduckgo.com/html/", params={"q": query})
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.warning("DuckDuckGo HTML search failed: %s", e)
            return out

        if BeautifulSoup:
            try:
                soup = BeautifulSoup(html, "html.parser")
                for node in soup.select(".result"):
                    a = node.select_one("a.result__a")
                    if not a:
                        continue
                    title = a.get_text(" ", strip=True)
                    href = self._clean_url(str(a.get("href") or "").strip())
                    snippet_node = node.select_one(".result__snippet")
                    snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
                    if title and href:
                        out.append(SearchResult(title=title, url=href, snippet=snippet))
                    if len(out) >= target:
                        break
                return out
            except Exception as e:
                logger.warning("DuckDuckGo parse (bs4) failed: %s", e)

        # Regex fallback
        try:
            matches = re.findall(
                r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?(?:<a[^>]*class="result__snippet"[^>]*>(.*?)</a>|<div[^>]*class="result__snippet"[^>]*>(.*?)</div>)?',
                html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            for href, title_html, snip_a, snip_div in matches:
                title = self._strip_tags(title_html).strip()
                snippet = self._strip_tags(snip_a or snip_div or "").strip()
                url = self._clean_url(href.strip())
                if title and url:
                    out.append(SearchResult(title=title, url=url, snippet=snippet))
                if len(out) >= target:
                    break
        except Exception as e:
            logger.warning("DuckDuckGo parse (regex) failed: %s", e)
        return out

    def _search_bing_html(self, query: str, *, target: int) -> list[SearchResult]:
        out: list[SearchResult] = []
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10.0),
                follow_redirects=True,
                headers={"User-Agent": self._USER_AGENT},
            ) as client:
                resp = client.get("https://www.bing.com/search", params={"q": query})
                resp.raise_for_status()
                html = resp.text
        except Exception as e:
            logger.warning("Bing web search failed: %s", e)
            return out

        if not BeautifulSoup:
            return out
        try:
            soup = BeautifulSoup(html, "html.parser")
            for li in soup.select("li.b_algo"):
                a = li.select_one("h2 a")
                if not a:
                    continue
                title = a.get_text(" ", strip=True)
                url = self._clean_url(str(a.get("href") or "").strip())
                snippet_node = li.select_one("p")
                snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""
                if title and url:
                    out.append(SearchResult(title=title, url=url, snippet=snippet))
                if len(out) >= target:
                    break
        except Exception as e:
            logger.warning("Bing parse failed: %s", e)
        return out

    def _search_bing_news_rss(self, query: str, *, target: int) -> list[SearchResult]:
        out: list[SearchResult] = []
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10.0),
                follow_redirects=True,
                headers={"User-Agent": self._USER_AGENT},
            ) as client:
                resp = client.get("https://www.bing.com/news/search", params={"q": query, "format": "rss"})
                resp.raise_for_status()
                xml = resp.text
            root = ET.fromstring(xml)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = self._clean_url((item.findtext("link") or "").strip())
                desc = (item.findtext("description") or "").strip()
                desc = self._strip_tags(desc)
                pub = (item.findtext("pubDate") or "").strip()
                pub_ts = self._parse_time(pub)
                if title and link:
                    out.append(SearchResult(title=title, url=link, snippet=desc, published_ts=pub_ts))
                if len(out) >= target:
                    break
        except Exception as e:
            logger.warning("Bing news RSS failed: %s", e)
        return out

    def fetch(
        self,
        results: List[SearchResult],
        mode: str = "fast",
        on_progress=None,
        *,
        prefer_rendered: bool = False,
    ) -> List[SearchResult]:
        """
        Fetch content for results, but keep snippet-only sources when fetch fails.
        This prevents a single failed crawl from collapsing the entire synthesis.
        """
        if not results:
            return []

        unique_results = self._dedupe_results(results, limit=len(results))
        workers = 4 if mode == "fast" else 8
        failed: list[SearchResult] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_result = {
                executor.submit(self._fetch_single_http, r, mode): r for r in unique_results
            }
            for future in concurrent.futures.as_completed(future_to_result):
                r = future_to_result[future]
                try:
                    content = (future.result() or "").strip()
                    if content:
                        r.content = content
                        if on_progress:
                            on_progress(f"Fetched {urlparse(r.url).netloc or r.url}")
                    else:
                        failed.append(r)
                        if on_progress:
                            on_progress(f"Using snippet only for {urlparse(r.url).netloc or r.url}")
                except Exception as e:
                    failed.append(r)
                    logger.warning("Fetch failed for %s: %s", r.url, e)

        needs_rendered = (mode == "deep" or prefer_rendered) and sync_playwright and failed
        if needs_rendered:
            # Limit rendered retries to keep deep mode bounded in latency.
            budget = min(len(failed), 3 if mode == "fast" else 8)
            self._fetch_rendered_batch(failed[:budget], on_progress=on_progress)

        return unique_results

    def _fetch_single_http(self, result: SearchResult, mode: str) -> str:
        timeout = 5.0 if mode == "fast" else 8.0
        try:
            with httpx.Client(
                timeout=httpx.Timeout(timeout),
                follow_redirects=True,
                headers={"User-Agent": self._USER_AGENT},
            ) as client:
                resp = client.get(result.url)
                resp.raise_for_status()
                ctype = (resp.headers.get("content-type") or "").lower()
                if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                    return ""
                html = resp.text
        except Exception:
            return ""

        text = self._extract_main_text(html)
        return self._clean_text(text)

    def _fetch_rendered_batch(self, results: list[SearchResult], on_progress=None) -> None:
        if not results or not sync_playwright:
            return

        timeout_ms = max(1_000, int(float(self.cfg.web.rendered_timeout_s) * 1000))
        wait_ms = max(0, int(self.cfg.web.rendered_wait_ms))
        try:
            with sync_playwright() as p:
                browser = self._launch_browser(p)
                context = browser.new_context(user_agent=self._USER_AGENT)
                page = context.new_page()

                for r in results:
                    try:
                        page.goto(r.url, wait_until="domcontentloaded", timeout=timeout_ms)
                        if wait_ms:
                            page.wait_for_timeout(wait_ms)
                        html = page.content()
                        text = self._extract_main_text(html)
                        if not text:
                            text = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
                        cleaned = self._clean_text(text)
                        if cleaned:
                            r.content = cleaned
                            if on_progress:
                                on_progress(f"Rendered {urlparse(r.url).netloc or r.url}")
                    except Exception as e:
                        logger.debug("Rendered fetch failed for %s: %s", r.url, e)
                context.close()
                browser.close()
        except Exception as e:
            logger.warning("Rendered fallback batch failed: %s", e)

    def _launch_browser(self, playwright):
        launch_args = {"headless": self.cfg.web.rendered_headless}
        if getattr(self.cfg.web, "rendered_prefer_chrome_channel", False):
            try:
                return playwright.chromium.launch(channel="chrome", **launch_args)
            except Exception:
                pass
        return playwright.chromium.launch(**launch_args)

    def rank(
        self,
        results: List[SearchResult],
        query: str,
        mode: str = "fast",
        *,
        prefer_news: bool = False,
        prefer_recent: bool = False,
    ) -> List[SearchResult]:
        if not results:
            return []

        q = (query or "").strip()
        is_news = bool(prefer_news)
        for r in results:
            basis = f"{r.title}\n{r.snippet}\n{(r.content or '')[:1400]}"
            r.score = self._lexical_score(q, basis)
            dom = self._domain(r.url)
            if dom in self._agg_domains:
                r.score *= 0.65
            if is_news and dom in self._preferred_news_domains:
                r.score += 0.08
            if prefer_recent and r.published_ts:
                r.score += self._recency_bonus(r.published_ts)

        # Fast mode favors latency; deep mode uses semantic reranking when available.
        if mode != "fast" and get_ranker:
            try:
                model = get_ranker()
                docs = [f"{r.title}\n{r.snippet}\n{(r.content or '')[:1200]}" for r in results]
                q_emb = model.encode(q, convert_to_tensor=True)
                d_embs = model.encode(docs, convert_to_tensor=True)
                sem_scores = util.cos_sim(q_emb, d_embs)[0]
                for i, r in enumerate(results):
                    semantic = float(sem_scores[i])
                    r.score = (0.65 * semantic) + (0.35 * r.score)
            except Exception as e:
                logger.warning("Semantic ranking failed; using lexical ranking only: %s", e)

        # Stable sort: ties keep original provider order.
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    def synthesize(
        self,
        query: str,
        results: List[SearchResult],
        llm_generate_fn,
        mode: str = "fast",
        *,
        prefer_news: bool = False,
        prefer_recent: bool = False,
        return_sources: bool = False,
    ):
        if not results:
            return "No results found to answer your query."

        top_k = 4 if mode == "fast" else 12
        max_content = 900 if mode == "fast" else 2000
        context: list[str] = []
        source_map: dict[str, str] = {}
        is_news = bool(prefer_news)
        if is_news and mode == "fast":
            max_per_domain = 1
        else:
            max_per_domain = 2
        selected = self._select_diverse(results, top_k=top_k, max_per_domain=max_per_domain)

        for r in selected:
            snippet = (r.snippet or "").strip()
            content = (r.content or "").strip()
            excerpt = (content[:max_content] if content else snippet[:600]).strip()
            if not excerpt:
                continue
            source_map[str(r.source_id)] = r.url
            context.append(
                f"Source [{r.source_id}]: {r.title}\n"
                f"URL: {r.url}\n"
                f"Snippet: {snippet}\n"
                f"Evidence: {excerpt}\n"
            )

        if not context:
            return "I found search hits but could not extract readable content from them."

        context_str = "\n---\n".join(context)
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        depth_line = (
            "Provide a concise answer first, then a deeper breakdown with key developments and implications."
            if mode == "deep"
            else "Keep it compact and direct."
        )

        time_sense_line = (
            "- If the query is time-sensitive, prioritize recent sources and explicitly mention uncertainty."
            if (prefer_recent or prefer_news)
            else ""
        )
        prompt = f"""You are a research assistant. Answer using only the provided sources.

User Local Date/Time: {current_time}
Query: {query}

Sources:
{context_str}

Instructions:
- {depth_line}
- Cite evidence as [Source ID].
- If evidence is thin or conflicting, say so clearly.
{time_sense_line}
- Do not hallucinate.
"""

        raw_answer = llm_generate_fn(system_prompt="You are a grounded web research assistant.", user_prompt=prompt) or ""
        if not raw_answer.strip():
            raw_answer = "I couldn't synthesize a full answer, but I found these sources."

        def replace_source(match):
            sid = match.group(1)
            suffix = match.group(2) or ""
            url = source_map.get(sid)
            if not url:
                return match.group(0)
            label = f"Source {sid}{suffix}"
            return f"[{label}]({url})"

        final_answer = re.sub(
            r"\[Source\s+(\d+)(:[^\]]*)?\]",
            replace_source,
            raw_answer,
            flags=re.IGNORECASE,
        )

        # If the model forgot citations, append explicit source links.
        if "[Source " not in final_answer and source_map:
            refs = "\n".join(
                f"- [Source {r.source_id}]({r.url})"
                for r in selected
                if str(r.source_id) in source_map
            )
            final_answer = f"{final_answer}\n\nSources:\n{refs}"

        final_answer = final_answer.strip()
        if return_sources:
            return final_answer, selected
        return final_answer

    @staticmethod
    def _is_news_query(query: str) -> bool:
        q = query.lower()
        markers = ("latest", "breaking", "news", "today", "headlines", "update")
        return any(m in q for m in markers)

    @staticmethod
    def _clean_text(text: str) -> str:
        if not text:
            return ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        out = "\n".join(lines)
        # Keep bounded evidence per source.
        return out[:10_000]

    @staticmethod
    def _lexical_score(query: str, text: str) -> float:
        q_tokens = re.findall(r"[a-z0-9]+", (query or "").lower())
        t_tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
        if not q_tokens or not t_tokens:
            return 0.0
        t_set = set(t_tokens)
        overlap = sum(1 for tok in q_tokens if tok in t_set)
        return overlap / max(1, len(set(q_tokens)))

    def _dedupe_results(self, results: list[SearchResult], limit: int) -> list[SearchResult]:
        deduped: list[SearchResult] = []
        seen: set[str] = set()
        for r in results:
            url = self._clean_url(r.url)
            if not url:
                continue
            key = self._canonical_key(url)
            if key in seen:
                continue
            seen.add(key)
            r.url = url
            deduped.append(r)
            if len(deduped) >= limit:
                break
        return deduped

    def _clean_url(self, url: str) -> str:
        url = (url or "").strip()
        if not url:
            return ""
        try:
            parsed = urlparse(url)
            if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
                qs = parse_qs(parsed.query or "")
                uddg = qs.get("uddg", [])
                if uddg:
                    return unquote(uddg[0])
        except Exception:
            pass
        return url

    @staticmethod
    def _canonical_key(url: str) -> str:
        try:
            p = urlparse(url)
            host = (p.netloc or "").lower()
            path = (p.path or "/").rstrip("/") or "/"
            return f"{host}{path}"
        except Exception:
            return url

    @staticmethod
    def _strip_tags(s: str) -> str:
        s = re.sub(r"<[^>]+>", " ", s or "")
        s = re.sub(r"\s+", " ", s)
        return s.strip()

    @staticmethod
    def _domain(url: str) -> str:
        try:
            host = (urlparse(url).netloc or "").lower()
            return host.lstrip("www.")
        except Exception:
            return ""

    def _select_diverse(self, results: list[SearchResult], top_k: int, max_per_domain: int) -> list[SearchResult]:
        if top_k <= 0:
            return []
        picked: list[SearchResult] = []
        per_domain: dict[str, int] = {}
        def try_pick(allow_agg: bool) -> None:
            nonlocal picked, per_domain
            for r in results:
                if len(picked) >= top_k:
                    break
                dom = self._domain(r.url)
                if not allow_agg and dom in self._agg_domains:
                    continue
                if dom:
                    if per_domain.get(dom, 0) >= max_per_domain:
                        continue
                    per_domain[dom] = per_domain.get(dom, 0) + 1
                picked.append(r)

        # Prefer non-aggregators first, then fill with aggregators if needed.
        try_pick(False)
        if len(picked) < top_k:
            try_pick(True)
        return picked

    @staticmethod
    def _parse_time(val) -> float | None:
        if not val:
            return None
        try:
            if isinstance(val, (int, float)):
                # Heuristic: ms epoch if large.
                if val > 10_000_000_000:
                    return float(val) / 1000.0
                return float(val)
            s = str(val).strip()
            if not s:
                return None
            # Try RFC822/RSS time
            try:
                dt = parsedate_to_datetime(s)
                return dt.timestamp()
            except Exception:
                pass
            # Try ISO-like
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                return dt.timestamp()
            except Exception:
                return None
        except Exception:
            return None

    @staticmethod
    def _recency_bonus(ts: float) -> float:
        try:
            age_s = max(0.0, datetime.now().timestamp() - ts)
            age_days = age_s / 86400.0
            # 0-2 days: strong bonus, decays over a week.
            if age_days <= 2:
                return 0.12
            if age_days <= 7:
                return 0.12 * (1.0 - (age_days - 2) / 5.0)
            return 0.0
        except Exception:
            return 0.0

    def _extract_main_text(self, html: str) -> str:
        if not html:
            return ""
        text = ""
        if trafilatura is not None:
            try:
                text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
            except Exception:
                text = ""
        if text:
            return text
        if BeautifulSoup:
            try:
                return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
            except Exception:
                return ""
        return self._strip_tags(html)
