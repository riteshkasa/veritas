import json
import re
from typing import Any, Optional

import httpx

from app.config import settings


_BASE = "https://generativelanguage.googleapis.com/v1beta"


class RateLimitError(Exception):
    """Raised on HTTP 429 from the Generative Language API."""


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from a model response.

    Gemma doesn't always honor `response_mime_type`, so we strip code fences
    and find the first JSON object/array in the text.
    """
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fallback: find the first {...} or [...] block.
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON found in model output: {text[:200]}")
    return json.loads(m.group(1))


class GemmaClient:
    """Minimal async client for Google's Generative Language API.

    Uses Gemma models for text generation. Supports a system+user prompt by
    prepending the system message to the user turn (Gemma has no system role).
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.gemma_api_key
        self.model = model or settings.verdict_model

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def chat_json(self, system: str, user: str, *, timeout: float = 20.0) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Gemma not configured")
        prompt = (
            f"{system}\n\n"
            f"USER INPUT:\n{user}\n\n"
            "Respond with ONLY a single JSON object. No prose, no code fences."
        )
        url = f"{_BASE}/models/{self.model}:generateContent?key={self.api_key}"
        gen_cfg: dict[str, Any] = {"temperature": 0.1}
        # `responseMimeType` is supported by Gemini models but rejected (400)
        # by Gemma. Only include it when we know it's safe.
        if self.model.lower().startswith("gemini"):
            gen_cfg["responseMimeType"] = "application/json"
        payload = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]},
            ],
            "generationConfig": gen_cfg,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 429:
                # Bubble up a typed exception so the caller can back off.
                raise RateLimitError(r.text[:200])
            r.raise_for_status()
            data = r.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"unexpected gemma response: {data}") from e
        return _extract_json(text)
