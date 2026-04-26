"""Groq Whisper transcription.

Free-tier-friendly OpenAI-compatible endpoint. Each call is one self-contained
audio segment (~5 s) -> a single transcription string.
"""
from __future__ import annotations

import httpx

from app.config import settings
from app.utils.logging import get_logger

log = get_logger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_MODEL = "whisper-large-v3-turbo"


async def transcribe(audio_bytes: bytes, mime: str = "audio/webm") -> str:
    """Return transcript text for one audio segment, or "" on failure."""
    if not settings.groq_api_key or not audio_bytes:
        return ""

    # Groq accepts standard audio container types. Pick a sensible filename
    # extension from the mime, since Groq sniffs based on filename too.
    ext = "webm"
    base = mime.split(";")[0].strip().lower()
    if "ogg" in base: ext = "ogg"
    elif "mp4" in base or "m4a" in base: ext = "m4a"
    elif "wav" in base: ext = "wav"
    elif "mpeg" in base or "mp3" in base: ext = "mp3"

    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    files = {"file": (f"segment.{ext}", audio_bytes, base or "audio/webm")}
    data = {
        "model": DEFAULT_MODEL,
        "language": "en",
        "response_format": "json",
        "temperature": "0",
    }

    log.info("groq whisper: POST bytes=%d ext=%s mime=%s", len(audio_bytes), ext, base)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(GROQ_URL, headers=headers, data=data, files=files)
        if r.status_code != 200:
            log.warning("groq whisper non-200 %s: %s", r.status_code, r.text[:300])
            return ""
        body = r.json()
        text = (body.get("text") or "").strip()
        log.info("groq whisper: 200 text_len=%d", len(text))
        return text
    except Exception as e:
        log.warning("groq whisper exception: %s", e)
        return ""
