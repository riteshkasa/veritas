"""Backend-side client for the fact-check uAgent.

Uses `uagents.communication.send_sync_message` with a stable backend Identity
so the receiving agent treats us as a verified sender. Falls back to a
low-confidence "unverified" result if the agent is unreachable / times out.
"""
from __future__ import annotations

from typing import Optional

from uagents.communication import send_sync_message
from uagents.resolver import RulesBasedResolver
from uagents_core.envelope import Envelope
from uagents_core.identity import Identity
from uagents_core.types import MsgStatus

from app.agents.schemas import FactCheckRequest, FactCheckResponse
from app.config import settings
from app.pipeline.schemas import Citation, VerdictResult
from app.utils.hashing import claim_hash
from app.utils.logging import get_logger

log = get_logger(__name__)


_BACKEND_IDENTITY: Optional[Identity] = None


def _identity() -> Identity:
    global _BACKEND_IDENTITY
    if _BACKEND_IDENTITY is None:
        seed = settings.factcheck_agent_seed or "niwas-backend-client-seed"
        _BACKEND_IDENTITY = Identity.from_seed(f"{seed}-client", 0)
        log.info("backend client identity address: %s", _BACKEND_IDENTITY.address)
    return _BACKEND_IDENTITY


async def check(
    claim: str,
    *,
    request_id: str,
    video_id: str = "",
    video_time_ms: int = 0,
    timeout: Optional[float] = None,
) -> VerdictResult:
    """Send a claim to the fact-check agent and return the resulting verdict."""
    address = settings.factcheck_agent_address
    if not address:
        log.warning("FACTCHECK_AGENT_ADDRESS not set; returning needs_context")
        return _fallback(claim, video_time_ms, "agent address not configured")

    timeout_s = int(timeout if timeout is not None else settings.factcheck_timeout_seconds)
    req = FactCheckRequest(
        claim=claim,
        video_id=video_id,
        video_time_ms=video_time_ms,
        request_id=request_id,
    )
    # Route directly to the agent's local HTTP server (port 8000)
    # instead of going through Agentverse mailbox, which is async-only
    # and doesn't support sync request/response.
    local_endpoint = settings.factcheck_agent_endpoint.replace(":8001", ":8000")
    resolver = RulesBasedResolver({address: [local_endpoint]})
    try:
        result = await send_sync_message(
            destination=address,
            message=req,
            response_type=FactCheckResponse,
            sender=_identity(),
            timeout=timeout_s,
            resolver=resolver,
        )
    except Exception as e:
        log.warning("factcheck client send_sync_message failed: %s", e)
        return _fallback(claim, video_time_ms, f"agent error: {e}")

    if isinstance(result, MsgStatus):
        log.warning("factcheck client returned MsgStatus: %s", result)
        return _fallback(claim, video_time_ms, f"agent status: {result}")

    if isinstance(result, Envelope):
        log.warning("factcheck client got bare envelope (response_type didn't match): %s",
                    result.decode_payload()[:200] if result.payload else "<empty>")
        return _fallback(claim, video_time_ms, "envelope without response type match")

    if not isinstance(result, FactCheckResponse):
        log.warning("factcheck client unexpected reply type %s: %r", type(result).__name__, result)
        return _fallback(claim, video_time_ms, f"unexpected reply type {type(result).__name__}")

    citations = [Citation(title=c.title, url=c.url, snippet=c.snippet) for c in result.citations]
    _valid_verdicts = {"true", "false", "misleading", "needs_context"}
    verdict = result.verdict.lower().strip() if result.verdict else "needs_context"
    if verdict not in _valid_verdicts:
        verdict = "needs_context"
    return VerdictResult(
        claim_id=request_id or claim_hash(claim),
        video_time_ms=video_time_ms,
        claim=result.claim or claim,
        verdict=verdict,  # type: ignore[arg-type]
        confidence=result.confidence,
        rationale=result.rationale,
        citations=citations,
    )


def _fallback(claim: str, video_time_ms: int, reason: str) -> VerdictResult:
    return VerdictResult(
        claim_id=claim_hash(claim or "empty"),
        video_time_ms=video_time_ms,
        claim=claim,
        verdict="needs_context",
        confidence=0.2,
        rationale=f"fact-check agent unavailable: {reason}",
        citations=[],
    )
