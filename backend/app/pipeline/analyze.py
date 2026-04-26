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
from app.pipeline.schemas import ChatOut, Citation, VerdictResult
from app.utils.hashing import claim_hash
from app.utils.logging import get_logger

log = get_logger(__name__)


EXTRACT_SYSTEM = (
    "You extract check-worthy factual claims from a short transcript chunk. "
    "You may also be given VIDEO CONTEXT (title, channel, published date, "
    "description) — use it to resolve pronouns (e.g. 'he' → the speaker's "
    "name) and to understand the topic, but do NOT extract claims from the "
    "metadata itself.\n\n"
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
    "2) For each claim, judge its veracity using your own knowledge. "
    "Pick exactly one verdict from: 'true', 'false', 'misleading', "
    "'needs_context'. NEVER return 'unknown' or 'unverified'. Always make "
    "your best-guess judgment. If a claim is inherently ambiguous or "
    "context-dependent, use 'needs_context' and present arguments from both "
    "sides. Provide a confidence in [0,1] and a 1–2 sentence rationale.\n\n"
    "Return JSON of the form:\n"
    "{\"claims\": [\n"
    "  {\"claim\": str, \"verdict\": \"true|false|misleading|needs_context\", "
    "\"confidence\": number, \"rationale\": str}\n"
    "]}\n"
    "If there are no check-worthy claims, return {\"claims\": []}. "
    "Output ONLY the JSON object."
)


VERDICT_WITH_EVIDENCE_SYSTEM = (
    "You judge a single factual claim given a small set of evidence snippets. "
    "Pick exactly one verdict from: 'true', 'false', 'misleading', "
    "'needs_context'.\n\n"
    "IMPORTANT RULES:\n"
    "- NEVER return 'unknown' or 'unverified' as a verdict. You must always "
    "commit to one of the four verdicts above.\n"
    "- If the provided evidence does NOT directly relate to the claim, use "
    "your own knowledge to make a best-guess verdict. State your reasoning "
    "clearly and set confidence based on how sure you are.\n"
    "- If a claim is inherently ambiguous or context-dependent (e.g. 'X policy "
    "is good for the economy'), use verdict 'needs_context' and present "
    "arguments from BOTH sides, citing sources for and against where possible. "
    "Explain what additional context would be needed to reach a definitive "
    "conclusion.\n"
    "- You should be reasonably certain in your verdicts. Only use low "
    "confidence (<0.5) when the claim is genuinely ambiguous, not because you "
    "lack evidence — in that case, use your own knowledge.\n\n"
    "CITATION RULES:\n"
    "- In your rationale, ALWAYS refer to sources by their actual name or title "
    "(e.g. 'According to the Wikipedia article on X…', 'Per NASA's official "
    "data…'). NEVER say 'evidence [1]' or 'evidence #3' — the user cannot see "
    "the evidence list, so numbered references are meaningless to them.\n"
    "- If you used your own knowledge instead of evidence, say so explicitly.\n\n"
    "Provide a confidence in [0,1] and a 1-2 sentence rationale.\n\n"
    "Return JSON of the form:\n"
    "{\"verdict\": \"true|false|misleading|needs_context\", "
    "\"confidence\": number, \"rationale\": str, "
    "\"citations\": [int, ...]}\n"
    "`citations` are 1-based indices into the evidence list you were given. "
    "Output ONLY the JSON object."
)


_VALID = {"true", "false", "misleading", "needs_context"}


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
        verdict = (c.get("verdict") or "needs_context").lower().strip()
        if verdict not in _VALID:
            verdict = "needs_context"
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


async def extract_claims(text: str, *, video_context: str = "") -> List[str]:
    """Return a list of standalone check-worthy claims from a transcript chunk.

    If `video_context` is provided (title, channel, date, description) it is
    prepended so the LLM can resolve pronouns and understand who is speaking.
    """
    text = text.strip()
    if not text:
        return []
    client = GemmaClient()
    if not client.enabled:
        log.warning("extract_claims: GEMMA_API_KEY not configured; skipping")
        return []
    user_msg = text
    if video_context:
        user_msg = f"VIDEO CONTEXT:\n{video_context}\n\nTRANSCRIPT:\n{text}"
    try:
        out = await client.chat_json(EXTRACT_SYSTEM, user_msg)
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
        verdict="needs_context",
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

    verdict = (out.get("verdict") or "needs_context").lower().strip()
    if verdict not in _VALID:
        verdict = "needs_context"
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


CHAT_SYSTEM = (
    "You are Veritas, an AI fact-checking assistant embedded in a YouTube video "
    "viewer. The user is watching a video and can ask you questions about claims "
    "made in the video, or any general knowledge questions.\n\n"
    "You have access to the recent transcript of the video the user is watching. "
    "Use it as context when relevant.\n\n"
    "IMPORTANT RULES:\n"
    "- Be concise and direct. Aim for 2-4 sentences unless the question demands "
    "more detail.\n"
    "- NEVER say 'unknown' or 'I don't know'. Always make your best-guess "
    "assessment based on your knowledge.\n"
    "- If a topic is genuinely ambiguous or context-dependent (e.g. 'is X good "
    "for the economy?'), present arguments from BOTH sides and explain what "
    "additional context would be needed.\n"
    "- If the provided transcript context doesn't relate to the question, answer "
    "from your own knowledge and say so.\n"
    "- Be reasonably certain in your answers. Express your confidence level when "
    "making factual claims.\n"
    "- Cite specific evidence or reasoning to support your answer.\n\n"
    "Return JSON of the form:\n"
    "{\"answer\": str}\n"
    "Output ONLY the JSON object."
)


async def chat(question: str, transcript_context: str = "") -> ChatOut:
    """Answer a free-form user question using Gemma, with optional transcript context."""
    question = (question or "").strip()
    if not question:
        return ChatOut(text="Please ask a question.", request_text=question)

    client = GemmaClient()
    if not client.enabled:
        return ChatOut(
            text="Chat is unavailable — GEMMA_API_KEY is not configured.",
            request_text=question,
        )

    user_msg = question
    if transcript_context:
        user_msg = (
            f"RECENT TRANSCRIPT:\n{transcript_context}\n\n"
            f"USER QUESTION:\n{question}"
        )

    try:
        out = await client.chat_json(CHAT_SYSTEM, user_msg, timeout=25.0)
    except Exception as e:
        log.warning("chat: LLM call failed: %s", e)
        return ChatOut(
            text="Sorry, I couldn't process that right now. Please try again.",
            request_text=question,
        )

    answer = str(out.get("answer") or out.get("text") or "").strip()
    if not answer:
        answer = "I wasn't able to generate a response. Please rephrase your question."

    return ChatOut(text=answer, request_text=question)
