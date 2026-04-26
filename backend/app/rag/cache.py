"""Local claim-verdict cache backed by SQLite.

Stores (claim text, embedding vector, evidence, verdict). On lookup, loads all
rows and picks the best cosine match if it clears the configured threshold.

This is deliberately simple so we can swap it for MongoDB Atlas vector search
later without touching callers; see `ClaimCache.search` / `ClaimCache.put`.
"""
from __future__ import annotations

import asyncio
import json
import math
import sqlite3
import struct
import time
from dataclasses import dataclass
from typing import List, Optional

from app.config import settings
from app.pipeline.schemas import Citation, VerdictResult
from app.utils.hashing import claim_hash
from app.utils.logging import get_logger

log = get_logger(__name__)


@dataclass
class CachedEntry:
    claim: str
    similarity: float
    verdict: str
    confidence: float
    rationale: str
    citations: List[Citation]


def _pack(vec: List[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes) -> List[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS claims (
    id TEXT PRIMARY KEY,
    claim TEXT NOT NULL,
    embedding BLOB NOT NULL,
    evidence_json TEXT NOT NULL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL,
    rationale TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class ClaimCache:
    """Async-friendly wrapper around a synchronous sqlite3 connection.

    All DB work runs on a thread via `asyncio.to_thread` so it doesn't block
    the event loop. Cheap enough for our size (tens of thousands of rows max).
    """

    def __init__(self, path: Optional[str] = None):
        self.path = path or settings.cache_db_path

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path)
        c.execute("PRAGMA journal_mode=WAL;")
        return c

    def _init(self) -> None:
        # `CREATE TABLE IF NOT EXISTS` is idempotent and very cheap, so we
        # run it every time. This makes the cache resilient to the DB file
        # being deleted out from under a long-running agent process.
        with self._conn() as c:
            c.executescript(_SCHEMA)

    async def search(
        self,
        embedding: List[float],
        *,
        top_k: int = 1,
        threshold: Optional[float] = None,
    ) -> Optional[CachedEntry]:
        """Return the best cached entry whose cosine similarity ≥ threshold."""
        if not embedding:
            return None
        threshold = settings.cache_sim_threshold if threshold is None else threshold

        def _work() -> Optional[CachedEntry]:
            self._init()
            with self._conn() as c:
                rows = c.execute(
                    "SELECT claim, embedding, evidence_json, verdict, confidence, rationale FROM claims"
                ).fetchall()
            best: Optional[CachedEntry] = None
            best_sim = 0.0
            for claim, emb_blob, evidence_json, verdict, confidence, rationale in rows:
                sim = _cosine(embedding, _unpack(emb_blob))
                if sim <= best_sim:
                    continue
                best_sim = sim
                try:
                    cites_raw = json.loads(evidence_json) or []
                    citations = [Citation(**c) for c in cites_raw]
                except Exception:
                    citations = []
                best = CachedEntry(
                    claim=claim,
                    similarity=sim,
                    verdict=verdict,
                    confidence=float(confidence),
                    rationale=rationale,
                    citations=citations,
                )
            if best and best.similarity >= threshold:
                log.info("cache hit sim=%.3f claim=%r", best.similarity, best.claim[:80])
                return best
            return None

        return await asyncio.to_thread(_work)

    async def put(
        self,
        claim: str,
        embedding: List[float],
        verdict: VerdictResult,
    ) -> None:
        """Insert or replace the cached entry for this claim."""
        if not embedding:
            return

        def _work() -> None:
            self._init()
            row_id = claim_hash(claim)
            evidence_json = json.dumps(
                [c.model_dump() for c in verdict.citations],
                ensure_ascii=False,
            )
            with self._conn() as c:
                c.execute(
                    """
                    INSERT INTO claims(id, claim, embedding, evidence_json,
                                       verdict, confidence, rationale, created_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        embedding=excluded.embedding,
                        evidence_json=excluded.evidence_json,
                        verdict=excluded.verdict,
                        confidence=excluded.confidence,
                        rationale=excluded.rationale,
                        created_at=excluded.created_at
                    """,
                    (
                        row_id,
                        claim,
                        _pack(embedding),
                        evidence_json,
                        verdict.verdict,
                        verdict.confidence,
                        verdict.rationale,
                        time.time(),
                    ),
                )

        await asyncio.to_thread(_work)
