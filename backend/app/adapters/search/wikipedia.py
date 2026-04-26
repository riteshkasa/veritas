"""Wikipedia evidence adapter.

No API key required. Uses:
  - opensearch for title candidates
  - page summary REST endpoint for a short extract
Returns a small list of `Citation` objects suitable for feeding to the LLM.
"""
from __future__ import annotations

from typing import List

import httpx

from app.pipeline.schemas import Citation
from app.utils.logging import get_logger

log = get_logger(__name__)

_API = "https://en.wikipedia.org/w/api.php"
_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"

_UA = "Niwas/0.1 (hackathon; fact-check cache)"


async def search(query: str, *, k: int = 3, timeout: float = 8.0) -> List[Citation]:
    """Full-text search Wikipedia for the claim and return short summaries.

    Uses `action=query&list=search` which is far better than `opensearch` for
    sentence-shaped queries — opensearch is autocomplete-style and rarely
    returns hits for full claims.
    """
    query = (query or "").strip()
    if not query:
        return []

    headers = {"User-Agent": _UA, "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            r = await client.get(
                _API,
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "srlimit": k,
                    "format": "json",
                },
            )
            r.raise_for_status()
            hits = (r.json().get("query") or {}).get("search") or []
            results: List[Citation] = []
            for h in hits[:k]:
                title = h.get("title") or ""
                if not title:
                    continue
                # Prefer the cleaner REST summary; fall back to the (HTML-tagged)
                # snippet from the search hit if the summary endpoint fails.
                snippet = ""
                page_url = ""
                try:
                    sr = await client.get(_SUMMARY + title.replace(" ", "_"))
                    if sr.status_code == 200:
                        sd = sr.json()
                        snippet = (sd.get("extract") or "").strip()
                        page_url = sd.get("content_urls", {}).get("desktop", {}).get("page") or ""
                except Exception as e:
                    log.debug("wiki summary failed for %r: %s", title, e)
                if not snippet:
                    raw = (h.get("snippet") or "").replace("<span class=\"searchmatch\">", "").replace("</span>", "")
                    snippet = raw.strip()
                if not page_url:
                    page_url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
                if snippet:
                    results.append(Citation(title=title, url=page_url, snippet=snippet[:600]))
            return results
    except Exception as e:
        log.warning("wikipedia search failed: %s", e)
        return []
