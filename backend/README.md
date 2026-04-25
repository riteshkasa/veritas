# Niwas Backend

FastAPI service exposing two WebSocket endpoints:

- `ws://HOST:PORT/ingest/captions` — extension streams caption cues here.
- `ws://HOST:PORT/ingest/audio` — extension streams `tabCapture` audio segments here.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # optional; without keys you get mock verdicts
python -m app.main
```

Health check: `curl http://localhost:8787/health`

## Env

- `GEMMA_API_KEY` — Google Generative Language API key. Used for:
  - Gemma model (default `gemma-3-27b-it`) → claim extraction + verdict judging.
  - Gemini model (default `gemini-2.0-flash`) → audio transcription, since Gemma is text-only.
- `TAVILY_API_KEY` — enables web search retrieval (Wikipedia is always on).
- `HOST`, `PORT`, `ALLOWED_ORIGINS`.

When `GEMMA_API_KEY` is unset, the pipeline still runs end-to-end but verdicts come back as `unverified` (mock mode) and audio transcripts are empty.
