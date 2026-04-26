#!/usr/bin/env python3
"""Quick smoke test for Groq's Whisper transcription endpoint.

Loads GROQ_API_KEY the same way the backend will (via pydantic-settings from
backend/.env), so once this works the real adapter will too.

Usage:
    python scripts/test_groq_whisper.py path/to/audio.{mp3,wav,m4a,webm,ogg,flac}

Optional flags:
    --model whisper-large-v3-turbo   (default; cheapest + fastest)
    --model whisper-large-v3         (highest quality)
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make `app` importable so we reuse the Settings loader -> backend/.env.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402


GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("audio", type=Path, help="path to an audio file")
    p.add_argument("--model", default="whisper-large-v3-turbo")
    p.add_argument("--language", default="en")
    args = p.parse_args()

    if not settings.groq_api_key:
        print(
            "ERROR: GROQ_API_KEY not found.\n"
            f"Looked in: {ROOT / 'backend' / '.env'} (working dir: {Path.cwd()}).\n"
            "Add a line like `GROQ_API_KEY=gsk_...` to backend/.env.",
            file=sys.stderr,
        )
        return 2

    audio_path: Path = args.audio
    if not audio_path.exists():
        print(f"ERROR: file not found: {audio_path}", file=sys.stderr)
        return 2

    print(f"file:   {audio_path} ({audio_path.stat().st_size:,} bytes)")
    print(f"model:  {args.model}")
    print(f"key:    {settings.groq_api_key[:8]}…{settings.groq_api_key[-4:]}")

    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    files = {"file": (audio_path.name, audio_path.read_bytes())}
    data = {
        "model": args.model,
        "language": args.language,
        # `json` returns just the text + metadata; `verbose_json` adds segments.
        "response_format": "json",
        "temperature": "0",
    }

    t0 = time.time()
    try:
        r = httpx.post(GROQ_URL, headers=headers, data=data, files=files, timeout=60.0)
    except httpx.HTTPError as e:
        print(f"ERROR: HTTP request failed: {e}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0

    print(f"status: {r.status_code} in {elapsed:.2f}s")
    if r.status_code != 200:
        print(r.text)
        return 1

    body = r.json()
    text = body.get("text", "")
    print("\n--- transcription ---")
    print(text.strip() or "(empty)")
    print("---------------------")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
