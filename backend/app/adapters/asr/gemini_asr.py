import base64
import httpx

from app.config import settings


_BASE = "https://generativelanguage.googleapis.com/v1beta"


async def transcribe(audio_bytes: bytes, mime: str = "audio/webm") -> str:
    """Transcribe a self-contained audio segment using a Gemini multimodal model.

    Gemma is text-only, so we use Gemini for ASR with the same Google API key.
    Returns empty string if no key is configured or on failure.
    """
    if not settings.has_llm or not audio_bytes:
        return ""

    # Gemini accepts a few audio mime types; normalize webm/opus -> audio/ogg
    # since some endpoints reject audio/webm. Most builds accept audio/webm fine.
    api_mime = mime.split(";")[0].strip() or "audio/webm"

    b64 = base64.b64encode(audio_bytes).decode("ascii")
    url = f"{_BASE}/models/{settings.asr_model}:generateContent?key={settings.gemma_api_key}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "Transcribe the following audio to English text. "
                            "Output ONLY the spoken words, with no commentary, "
                            "no timestamps, and no quotation marks. "
                            "If the audio is silent or unintelligible, respond "
                            "with an empty string."
                        )
                    },
                    {"inline_data": {"mime_type": api_mime, "data": b64}},
                ],
            }
        ],
        "generationConfig": {"temperature": 0.0},
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            r = await client.post(url, json=payload)
            r.raise_for_status()
            data = r.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return (text or "").strip()
        except Exception:
            return ""
