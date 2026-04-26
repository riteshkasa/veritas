#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d backend/.venv ]; then
  uv venv backend/.venv
fi
source backend/.venv/bin/activate
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
uv pip install -r backend/requirements.txt
exec python scripts/run_factcheck_agent.py
