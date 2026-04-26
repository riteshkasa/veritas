#!/usr/bin/env python3
"""End-to-end smoke test against a running fact-check uAgent.

Prereqs:
  1. `python scripts/run_factcheck_agent.py` running in another terminal.
  2. The agent address from that script copied into FACTCHECK_AGENT_ADDRESS in
     backend/.env.

Sends one claim through the agent and prints the verdict + citations.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.factcheck_client import check  # noqa: E402
from app.config import settings  # noqa: E402


async def main() -> int:
    if not settings.factcheck_agent_address:
        print("ERROR: FACTCHECK_AGENT_ADDRESS not set in backend/.env", file=sys.stderr)
        return 2

    claim = " ".join(sys.argv[1:]) or "The Eiffel Tower is 330 meters tall including antennas."
    print(f"claim: {claim!r}")
    print(f"agent: {settings.factcheck_agent_address}")
    result = await check(claim, request_id="smoke-test")
    print(f"\nverdict:    {result.verdict}")
    print(f"confidence: {result.confidence:.2f}")
    print(f"rationale:  {result.rationale}")
    print(f"citations:  {len(result.citations)}")
    for i, c in enumerate(result.citations, 1):
        print(f"  [{i}] {c.title}\n      {c.url}\n      {c.snippet[:140]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
