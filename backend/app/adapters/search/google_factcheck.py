"""Google Fact Check Tools API adapter.

Docs: https://developers.google.com/fact-check/tools/api/reference/rest/v1alpha1/claims/search

The API key must belong to a project where the Fact Check Tools API is enabled
in the Google Cloud console. We fall back to the Gemma key if no dedicated key
is configured (same Google project).
"""
from __future__ import annotations

from typing import List

import httpx

from app.config import settings
from app.pipeline.schemas import Citation
from app.utils.logging import get_logger

log = get_logger(__name__)

_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


async def search(query: str, *, k: int = 5, timeout: float = 8.0) -> List[Citation]:
    query = (query or "").strip()
    key = settings.factcheck_key
    if not query or not key:
        return []
    params = {"query": query, "pageSize": k, "languageCode": "en", "key": key}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(_URL, params=params)
        if r.status_code != 200:
            log.warning("google factcheck non-200 %s: %s", r.status_code, r.text[:200])
            return []
        data = r.json()
    except Exception as e:
        log.warning("google factcheck error: %s", e)
        return []

    results: List[Citation] = []
    for c in data.get("claims", []) or []:
        claim_text = (c.get("text") or "").strip()
        for rev in c.get("claimReview", []) or []:
            publisher = (rev.get("publisher") or {}).get("name") or "Fact check"
            rating = (rev.get("textualRating") or "").strip()
            url = rev.get("url") or ""
            title = rev.get("title") or f"{publisher}: {rating or 'fact check'}"
            snippet_parts = [p for p in [claim_text, rating] if p]
            snippet = " — ".join(snippet_parts)[:600]
            if url and snippet:
                results.append(Citation(title=title, url=url, snippet=snippet))
            if len(results) >= k:
                break
        if len(results) >= k:
            break
    return results
