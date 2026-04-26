#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [ ! -d .venv ]; then
  uv venv .venv
fi
source .venv/bin/activate
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
uv pip install -r requirements.txt
# Disable WatchFiles reloader: it spawns a subprocess that fails to import
# `google.protobuf` once cosmpy (a uagents transitive dep) is on the path.
# Code edits while this is running will require a manual restart.
export NIWAS_NO_RELOAD=1
exec python -m app.main
