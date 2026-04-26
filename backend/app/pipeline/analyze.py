"""LLM-powered claim extraction and (optionally) verdict judgment.

Two public entry points:
  - `extract_claims(text)` -> [str]           : just pulls check-worthy claims.
  - `analyze(text, video_time_ms)` -> [VR]    : LEGACY self-contained path that
    judges each claim from Gemma's own knowledge (no retrieval). Kept so the
    existing orchestrator keeps working if the uAgent path is disabled.

Retrieval-backed verdicts are produced by the fact-check uAgent (see
`app.agents.factcheck_agent`).
"""
from typing import List

from app.adapters.llm.gemma_client import GemmaClient
from app.pipeline.schemas import Citation, VerdictResult
from app.utils.hashing import claim_hash
from app.utils.logging import get_logger

log = get_logger(__name__)


EXTRACT_SYSTEM = (
    "You extract check-worthy factual claims from a short transcript chunk. "
    "A check-worthy claim is a specific, verifiable assertion about the real "
    "world: numbers, dates, named people / orgs / places, causal statements, "
    "scientific or historical facts. Skip opinions, jokes, questions, "
    "hypotheticals, ad copy, and chit-chat. Resolve pronouns where obvious. "
    "Rewrite each claim as a standalone sentence that can be fact-checked in "
    "isolation (no 'he', 'this', 'that').\n\n"
    "Return JSON of the form {\"claims\": [\"...\", \"...\"]}. "
    "If there are no check-worthy claims, return {\"claims\": []}. "
    "Output ONLY the JSON object."
)


LEGACY_SYSTEM = (
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


VERDICT_WITH_EVIDENCE_SYSTEM = (
    "You judge a single factual claim given a small set of evidence snippets. "
    "Pick exactly one verdict from: 'true', 'false', 'misleading', "
    "'unverified'. Use 'unverified' if the evidence is insufficient. "
    "Provide a confidence in [0,1] and a 1-2 sentence rationale that explicitly "
    "cites the evidence indices you relied on (e.g. \"[1], [3]\").\n\n"
    "Return JSON of the form:\n"
    "{\"verdict\": \"true|false|misleading|unverified\", "
    "\"confidence\": number, \"rationale\": str, "
    "\"citations\": [int, ...]}\n"
    "`citations` are 1-based indices into the evidence list you were given. "
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
        out = await client.chat_json(LEGACY_SYSTEM, text)
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


async def extract_claims(text: str) -> List[str]:
    """Return a list of standalone check-worthy claims from a transcript chunk."""
    text = text.strip()
    if not text:
        return []
    client = GemmaClient()
    if not client.enabled:
        log.warning("extract_claims: GEMMA_API_KEY not configured; skipping")
        return []
    try:
        out = await client.chat_json(EXTRACT_SYSTEM, text)
    except Exception as e:
        log.warning("extract_claims: LLM call failed: %s", e)
        return []
    raw = out.get("claims") or []
    claims: List[str] = []
    for item in raw:
        if isinstance(item, str):
            s = item.strip()
        elif isinstance(item, dict):
            s = (item.get("claim") or "").strip()
        else:
            continue
        if s and len(s) >= 10:
            claims.append(s)
    return claims


async def verdict_with_evidence(claim: str, evidence: List[Citation]) -> VerdictResult:
    """Ask Gemma for a verdict on `claim` given a list of `evidence` citations.

    Returns an `unverified` low-confidence result on any error, so callers can
    safely assume a result object comes back.
    """
    claim = (claim or "").strip()
    fallback = VerdictResult(
        claim_id=claim_hash(claim or "empty"),
        video_time_ms=0,
        claim=claim,
        verdict="unverified",
        confidence=0.3,
        rationale="No evidence available or LLM call failed.",
        citations=list(evidence),
    )
    if not claim:
        return fallback
    client = GemmaClient()
    if not client.enabled:
        return fallback

    if evidence:
        evidence_block = "\n".join(
            f"[{i+1}] {c.title} — {c.snippet} (source: {c.url})"
            for i, c in enumerate(evidence)
        )
    else:
        evidence_block = "(no evidence retrieved)"
    user = f"CLAIM:\n{claim}\n\nEVIDENCE:\n{evidence_block}"
    try:
        out = await client.chat_json(VERDICT_WITH_EVIDENCE_SYSTEM, user)
    except Exception as e:
        log.warning("verdict_with_evidence: LLM call failed: %s", e)
        return fallback

    verdict = (out.get("verdict") or "unverified").lower().strip()
    if verdict not in _VALID:
        verdict = "unverified"
    try:
        confidence = float(out.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    rationale = str(out.get("rationale") or "")[:600]

    # Map 1-based citation indices back to the actual evidence list.
    cite_idxs = out.get("citations") or []
    kept: List[Citation] = []
    for i in cite_idxs:
        try:
            n = int(i) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= n < len(evidence):
            kept.append(evidence[n])
    # If the model cited nothing but we DO have evidence, include all of it
    # so the UI still renders sources.
    if not kept and evidence:
        kept = list(evidence)

    return VerdictResult(
        claim_id=claim_hash(claim),
        video_time_ms=0,
        claim=claim,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=confidence,
        rationale=rationale,
        citations=kept,
    )
