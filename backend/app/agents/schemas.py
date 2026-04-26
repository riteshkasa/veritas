"""Message types exchanged with the fact-check uAgent."""
from __future__ import annotations

from typing import List

from uagents import Model


class CitationOut(Model):
    title: str = ""
    url: str = ""
    snippet: str = ""


class FactCheckRequest(Model):
    claim: str
    video_id: str = ""
    video_time_ms: int = 0
    # Correlation id echoed back in the response; we use the backend's claim_id.
    request_id: str = ""


class FactCheckResponse(Model):
    request_id: str
    claim: str
    verdict: str  # true | false | misleading | unverified
    confidence: float
    rationale: str = ""
    citations: List[CitationOut] = []
    from_cache: bool = False
    video_time_ms: int = 0
