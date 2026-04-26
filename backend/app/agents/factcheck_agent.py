"""Fact-check uAgent.

Receives `FactCheckRequest`s from the backend, performs the retrieval + verdict
pipeline, writes results to the local vector cache, and replies with a
`FactCheckResponse`.

Run via `python scripts/run_factcheck_agent.py`.
"""
from __future__ import annotations

import asyncio

import aiohttp
from uagents import Agent, Context

from app.adapters.embeddings.gemini import embed
from app.adapters.search import google_factcheck, wikipedia
from app.agents.schemas import CitationOut, FactCheckRequest, FactCheckResponse
from app.config import settings
from app.pipeline.analyze import verdict_with_evidence
from app.pipeline.schemas import Citation
from app.rag.cache import ClaimCache
from app.utils.logging import get_logger

log = get_logger(__name__)


_cache = ClaimCache()


def _to_citation_out(cs: list[Citation]) -> list[CitationOut]:
    return [CitationOut(title=c.title, url=c.url, snippet=c.snippet) for c in cs]


def _to_citation(cs: list[CitationOut]) -> list[Citation]:
    return [Citation(title=c.title, url=c.url, snippet=c.snippet) for c in cs]


async def _gather_evidence(claim: str) -> list[Citation]:
    wiki_task = wikipedia.search(claim, k=3)
    fc_task = google_factcheck.search(claim, k=3)
    wiki, fc = await asyncio.gather(wiki_task, fc_task, return_exceptions=True)
    evidence: list[Citation] = []
    if isinstance(wiki, list):
        evidence.extend(wiki)
    if isinstance(fc, list):
        evidence.extend(fc)
    return evidence


def _build_agent() -> Agent:
    seed = settings.factcheck_agent_seed or "niwas-factcheck-dev-seed"
    # mailbox=True tells uagents to add the Agentverse mailbox endpoint
    # to this agent's endpoint list so it's treated as a mailbox agent.
    # The mailbox still needs to be *created* on Agentverse via the /connect
    # REST endpoint the SDK exposes on the agent's local HTTP server.
    agent = Agent(
        name="niwas-factcheck",
        seed=seed,
        mailbox=True,
    )

    @agent.on_event("startup")
    async def _on_startup(ctx: Context) -> None:
        ctx.logger.info("fact-check agent address: %s", agent.address)
        ctx.logger.info("cache db: %s", settings.cache_db_path)

        # Auto-register with Agentverse if we have an API key.
        # This POSTs to the agent's own /connect REST handler which
        # does the challenge/response dance with Agentverse and
        # creates the mailbox.  Equivalent to clicking "Connect" in
        # the inspector UI.
        api_key = settings.agentverse_mailbox_key
        if api_key:
            local_url = f"http://127.0.0.1:{agent._port}/connect"
            payload = {
                "user_token": api_key,
                "agent_type": "mailbox",
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(local_url, json=payload) as resp:
                        body = await resp.json()
                        if body.get("success"):
                            ctx.logger.info(
                                "Mailbox registered on Agentverse successfully"
                            )
                        else:
                            ctx.logger.warning(
                                "Agentverse registration failed: %s",
                                body.get("detail", body),
                            )
            except Exception as exc:
                ctx.logger.error("Auto-register with Agentverse failed: %s", exc)

    @agent.on_message(model=FactCheckRequest, replies=FactCheckResponse)
    async def _handle(ctx: Context, sender: str, msg: FactCheckRequest) -> None:
        ctx.logger.info("fact-check: claim=%r", msg.claim[:120])
        claim = (msg.claim or "").strip()
        if not claim:
            await ctx.send(sender, FactCheckResponse(
                request_id=msg.request_id,
                claim="",
                verdict="unverified",
                confidence=0.0,
                rationale="empty claim",
                video_time_ms=msg.video_time_ms,
            ))
            return

        # 1) Embed + cache lookup.
        q_emb = await embed(claim, task_type="RETRIEVAL_QUERY")
        cached = await _cache.search(q_emb) if q_emb else None
        if cached is not None:
            ctx.logger.info("cache hit sim=%.3f", cached.similarity)
            await ctx.send(sender, FactCheckResponse(
                request_id=msg.request_id,
                claim=claim,
                verdict=cached.verdict,
                confidence=cached.confidence,
                rationale=cached.rationale,
                citations=_to_citation_out(cached.citations),
                from_cache=True,
                video_time_ms=msg.video_time_ms,
            ))
            return

        # 2) Gather evidence.
        evidence = await _gather_evidence(claim)
        ctx.logger.info("evidence: %d items", len(evidence))

        # 3) LLM verdict given evidence.
        vr = await verdict_with_evidence(claim, evidence)

        # 4) Store back in cache (reusing the query embedding).
        if q_emb:
            try:
                await _cache.put(claim, q_emb, vr)
            except Exception as e:
                ctx.logger.warning("cache put failed: %s", e)

        await ctx.send(sender, FactCheckResponse(
            request_id=msg.request_id,
            claim=claim,
            verdict=vr.verdict,
            confidence=vr.confidence,
            rationale=vr.rationale,
            citations=_to_citation_out(vr.citations),
            from_cache=False,
            video_time_ms=msg.video_time_ms,
        ))

    return agent


agent = _build_agent()
