#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
# Disable WatchFiles reloader: it spawns a subprocess that fails to import
# `google.protobuf` once cosmpy (a uagents transitive dep) is on the path.
# Code edits while this is running will require a manual restart.
export NIWAS_NO_RELOAD=1
exec python -m app.main
