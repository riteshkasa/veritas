"""Single-call LLM analyzer.

Given a chunk of transcript text, returns a list of (claim, verdict) judgments
based purely on the model's own knowledge. No retrieval / web search.
"""
from typing import List

from app.adapters.llm.gemma_client import GemmaClient
from app.pipeline.schemas import VerdictResult
from app.utils.hashing import claim_hash
from app.utils.logging import get_logger

log = get_logger(__name__)


SYSTEM = (
    "You are a real-time fact-checking assistant. You will be given a short "
    "transcript chunk from a video. Do TWO things:\n"
    "1) Extract every distinct CHECK-WORTHY factual claim. A check-worthy "
    "claim is a specific, verifiable assertion about the real world — "
    "numbers, dates, named people / orgs / places, causal statements, "
    "scientific or historical facts. Skip opinions, jokes, questions, "
    "hypotheticals, ad copy, and chit-chat. Resolve pronouns where obvious.\n"
    "2) For each claim, judge its veracity using only your own knowledge. "
    "Pick exactly one verdict from: 'true', 'false', 'misleading', "
    "'unverified'. Use 'unverified' ONLY when you genuinely do not know. "
    "Provide a confidence in [0,1] and a 1–2 sentence rationale.\n\n"
    "Return JSON of the form:\n"
    "{\"claims\": [\n"
    "  {\"claim\": str, \"verdict\": \"true|false|misleading|unverified\", "
    "\"confidence\": number, \"rationale\": str}\n"
    "]}\n"
    "If there are no check-worthy claims, return {\"claims\": []}. "
    "Output ONLY the JSON object."
)


_VALID = {"true", "false", "misleading", "unverified"}


async def analyze(text: str, video_time_ms: int) -> List[VerdictResult]:
    text = text.strip()
    if not text:
        return []
    client = GemmaClient()
    if not client.enabled:
        log.warning("analyze: GEMMA_API_KEY not configured; skipping")
        return []

    try:
        out = await client.chat_json(SYSTEM, text)
    except Exception as e:
        log.warning("analyze: LLM call failed: %s", e)
        return []

    raw_claims = out.get("claims") or []
    results: List[VerdictResult] = []
    for c in raw_claims:
        if not isinstance(c, dict):
            continue
        claim_text = (c.get("claim") or "").strip()
        if not claim_text:
            continue
        verdict = (c.get("verdict") or "unverified").lower().strip()
        if verdict not in _VALID:
            verdict = "unverified"
        try:
            confidence = float(c.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence))
        rationale = str(c.get("rationale") or "")[:600]
        results.append(
            VerdictResult(
                claim_id=claim_hash(claim_text),
                video_time_ms=video_time_ms,
                claim=claim_text,
                verdict=verdict,  # type: ignore[arg-type]
                confidence=confidence,
                rationale=rationale,
                citations=[],
            )
        )
    return results
