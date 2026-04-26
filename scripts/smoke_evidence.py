#!/usr/bin/env python3
"""Smoke-test Wikipedia and Google Fact Check adapters."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.search import google_factcheck, wikipedia  # noqa: E402
from app.config import settings  # noqa: E402


async def main() -> int:
    queries = sys.argv[1:] or [
        "The Eiffel Tower is 330 meters tall",
        "Vaccines cause autism",
    ]
    for q in queries:
        print(f"\n=== query: {q!r} ===")
        print("-- wikipedia --")
        for c in await wikipedia.search(q, k=2):
            print(f"  {c.title}\n    {c.url}\n    {c.snippet[:140]}…")
        print("-- google factcheck --")
        if not settings.factcheck_key:
            print("  (skipped: no google factcheck key configured)")
            continue
        cites = await google_factcheck.search(q, k=3)
        if not cites:
            print("  (no results)")
        for c in cites:
            print(f"  {c.title}\n    {c.url}\n    {c.snippet[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
