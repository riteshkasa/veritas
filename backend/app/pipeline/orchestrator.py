import asyncio
import time
from typing import Awaitable, Callable, List, Tuple

from app.adapters.llm.gemma_client import RateLimitError
from app.config import settings
from app.pipeline.analyze import analyze
from app.pipeline.schemas import StatusOut, TranscriptOut
from app.utils.logging import get_logger

log = get_logger(__name__)


SendFn = Callable[[dict], Awaitable[None]]


class Session:
    """Per-connection orchestrator: text in -> verdicts out.

    Cues / transcript fragments are appended to an in-memory queue. A single
    background worker drains the queue every `analyze_interval_seconds`,
    deduplicates overlapping CC text, and makes ONE LLM call per window.
    On 429 it doubles its interval (capped) until calls succeed again.
    """

    def __init__(self, session_id: str, video_id: str, send: SendFn):
        self.session_id = session_id
        self.video_id = video_id
        self.send = send
        self.queue: List[Tuple[int, str]] = []  # (video_time_ms, text)
        self.seen_claims: set[str] = set()
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._interval = float(settings.analyze_interval_seconds)
        self._min_gap = float(settings.min_llm_interval_seconds)
        self._last_call_at = 0.0

    # ---- public ----
    async def feed(self, text: str, time_ms: int) -> None:
        text = (text or "").strip()
        if not text:
            return
        # Live transcript echo for the UI.
        await self.send(TranscriptOut(text=text, video_time_ms=time_ms).model_dump())
        self.queue.append((time_ms, text))
        if self._task is None:
            self._task = asyncio.create_task(self._worker())

    async def flush(self) -> None:
        await self._drain_once(force=True)

    async def close(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except Exception:
                pass

    # ---- internal ----
    async def _worker(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
                    break  # stop signaled
                except asyncio.TimeoutError:
                    pass
                await self._drain_once()
        except Exception as e:
            log.exception("worker crashed: %s", e)

    async def _drain_once(self, *, force: bool = False) -> None:
        if not self.queue:
            return
        now = time.time()
        if not force and (now - self._last_call_at) < self._min_gap:
            return

        # Pop everything currently queued.
        items, self.queue = self.queue, []
        chunk = _merge_cues(items)
        if len(chunk) < settings.min_chunk_chars and not force:
            # Too little to be worth a call; put it back for the next window.
            self.queue = items + self.queue
            return

        first_time_ms = items[0][0]
        self._last_call_at = now
        log.info(
            "analyze window: %d cues, %d chars, interval=%.1fs",
            len(items), len(chunk), self._interval,
        )

        try:
            results = await analyze(chunk, first_time_ms)
        except RateLimitError as e:
            old = self._interval
            self._interval = min(self._interval * 2, 120.0)
            self._min_gap = min(self._min_gap * 2, 120.0)
            log.warning("429 from LLM; backing off %.1fs -> %.1fs (%s)", old, self._interval, e)
            await self.send(StatusOut(
                level="warn",
                message=f"LLM rate-limited; slowing to {int(self._interval)}s windows",
            ).model_dump())
            return
        except Exception as e:
            log.exception("analyze failed: %s", e)
            return

        # Success -> gradually relax backoff back to defaults.
        if self._interval > settings.analyze_interval_seconds:
            self._interval = max(settings.analyze_interval_seconds, self._interval * 0.7)
            self._min_gap = max(settings.min_llm_interval_seconds, self._min_gap * 0.7)

        for r in results:
            if r.claim_id in self.seen_claims:
                continue
            self.seen_claims.add(r.claim_id)
            await self.send(r.model_dump())
            log.info("verdict %s: %s (%.2f) — %s", r.claim_id, r.verdict, r.confidence, r.claim[:80])


def _merge_cues(items: List[Tuple[int, str]]) -> str:
    """Join cues into one chunk while collapsing overlapping/duplicate text.

    YouTube captions often re-emit growing prefixes; even with the frontend
    deduper, two adjacent cues can overlap. We merge greedily by stripping
    any prefix of the new cue that already appears at the tail of the
    accumulated text.
    """
    out = ""
    for _, text in items:
        text = " ".join(text.split())
        if not text:
            continue
        if not out:
            out = text
            continue
        # Find longest overlap between end of `out` and start of `text`.
        max_k = min(len(out), len(text))
        overlap = 0
        for k in range(max_k, 0, -1):
            if out.endswith(text[:k]):
                overlap = k
                break
        out = (out + " " + text[overlap:]).strip()
    return out
