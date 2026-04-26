#!/usr/bin/env python3
"""Run the Niwas fact-check uAgent.

Reads config from backend/.env. The first run prints the agent's address;
copy it into FACTCHECK_AGENT_ADDRESS in backend/.env so the backend client
can target it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.factcheck_agent import agent  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> None:
    print(f"fact-check agent address: {agent.address}")
    print(f"endpoint: {settings.factcheck_agent_endpoint}")
    print(f"cache db: {settings.cache_db_path}")
    agent.run()


if __name__ == "__main__":
    main()
