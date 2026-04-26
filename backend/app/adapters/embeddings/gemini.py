"""Gemini text embeddings.

Uses the Google Generative Language API's `text-embedding-004` model with the
existing GEMMA_API_KEY. 768-dim float vectors.
"""
from __future__ import annotations

from typing import List

import httpx

from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)

_BASE = "https://generativelanguage.googleapis.com/v1beta"


async def embed(text: str, *, task_type: str = "RETRIEVAL_DOCUMENT", timeout: float = 15.0) -> List[float]:
    """Return the embedding vector for `text`, or [] on failure.

    `task_type` should be "RETRIEVAL_DOCUMENT" when storing, "RETRIEVAL_QUERY"
    when searching. Using the matching types improves cosine similarity.
    """
    if not settings.gemma_api_key or not text.strip():
        return []
    url = f"{_BASE}/models/{settings.embedding_model}:embedContent?key={settings.gemma_api_key}"
    payload = {
        "model": f"models/{settings.embedding_model}",
        "content": {"parts": [{"text": text}]},
        "taskType": task_type,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload)
        if r.status_code != 200:
            log.warning("gemini embed non-200 %s: %s", r.status_code, r.text[:200])
            return []
        body = r.json()
        values = (body.get("embedding") or {}).get("values") or []
        return [float(v) for v in values]
    except Exception as e:
        log.warning("gemini embed error: %s", e)
        return []
