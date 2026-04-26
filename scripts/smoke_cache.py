#!/usr/bin/env python3
"""Smoke-test Gemini embeddings + SQLite claim cache.

Stores one claim/verdict, then searches with a paraphrased query and a
completely unrelated query. Expects the paraphrase to hit, the unrelated to
miss.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.adapters.embeddings.gemini import embed  # noqa: E402
from app.config import settings  # noqa: E402
from app.pipeline.schemas import Citation, VerdictResult  # noqa: E402
from app.rag.cache import ClaimCache  # noqa: E402


async def main() -> int:
    if not settings.gemma_api_key:
        print("ERROR: GEMMA_API_KEY not set in backend/.env", file=sys.stderr)
        return 2

    # Use a scratch DB so we don't pollute the real cache.
    db_path = "/tmp/niwas_cache_smoke.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    cache = ClaimCache(path=db_path)

    stored_claim = "The Eiffel Tower is 330 meters tall including antennas."
    verdict = VerdictResult(
        claim_id="seed",
        video_time_ms=0,
        claim=stored_claim,
        verdict="true",
        confidence=0.95,
        rationale="Cached test entry.",
        citations=[Citation(title="Wikipedia", url="https://en.wikipedia.org/wiki/Eiffel_Tower", snippet="330 m")],
    )

    print("embedding + storing seed claim…")
    emb = await embed(stored_claim, task_type="RETRIEVAL_DOCUMENT")
    if not emb:
        print("ERROR: embedding returned empty (bad key?)", file=sys.stderr)
        return 1
    print(f"  dim={len(emb)}")
    await cache.put(stored_claim, emb, verdict)

    paraphrase = "Counting its antennas, the Eiffel Tower stands at 330 meters."
    unrelated = "The Python programming language was created by Guido van Rossum."

    for label, q in [("paraphrase", paraphrase), ("unrelated", unrelated)]:
        q_emb = await embed(q, task_type="RETRIEVAL_QUERY")
        # Use threshold=0.0 so we always see the best similarity for diagnosis.
        hit = await cache.search(q_emb, threshold=0.0)
        sim = hit.similarity if hit else 0.0
        above = sim >= settings.cache_sim_threshold
        print(f"[{label}] best_sim={sim:.3f} hits_threshold({settings.cache_sim_threshold})={above}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
