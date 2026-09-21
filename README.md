# Veritas — Real-Time Video Fact Checker

A Chrome extension that fact-checks YouTube videos in real time. Closed captions are streamed to a FastAPI backend where Google Gemma extracts check-worthy claims; a Fetch.ai uAgent gathers evidence from Wikipedia and Google Fact Check Tools, consults a semantic vector cache, and renders verdicts with citations. An integrated chat lets you ask questions about the video as you watch.

[Veritas LA Hacks Video](https://www.youtube.com/watch?v=CuinBraRAlk&feature=youtu.be)

## Features

- **Live fact-checking** — Claims are extracted from captions automatically and checked against real sources.
- **Verdict cards** — Color-coded results (`true`, `false`, `misleading`, `needs_context`) with confidence scores, rationale, and source links.
- **Ask Veritas** — Chat with an AI assistant that has context from the video transcript.
- **Semantic cache** — SQLite + Gemini embeddings so paraphrased claims are answered instantly.
- **Video-aware** — Scrapes video title, channel, description, and publish date to help the LLM resolve pronouns and understand context.
- **Expandable UI** — Draggable, collapsible panel with a resizable split between fact-check results and chat.

## Quick Start

### 1. Backend

```bash
cd backend
cp ../.env.example .env          # fill in API keys
./scripts/dev-backend.sh
```

Health check: `curl http://localhost:8787/health`

### 2. Fact-check uAgent

In a separate terminal:

```bash
./scripts/dev-agent.sh
```

The first run prints an `agent1q...` address. Set it in `backend/.env`:

```
FACTCHECK_AGENT_SEED=any-stable-phrase
FACTCHECK_AGENT_ADDRESS=agent1q...
```

Then restart the agent. Smoke test:

```bash
backend/.venv/bin/python scripts/test_factcheck_agent.py "The Eiffel Tower is 330 meters tall"
```

### 3. Chrome Extension

1. Open `chrome://extensions` → enable **Developer mode**.
2. **Load unpacked** → select the `extension/` folder.
3. Open a YouTube video. The **Veritas** panel appears.
4. Click **Start**.

## Configuration

Set in `backend/.env` (see `.env.example`):

| Variable | Purpose |
| --- | --- |
| `GEMMA_API_KEY` | Google API key for Gemma (claims + verdicts) and Gemini (embeddings) |
| `GOOGLE_FACTCHECK_API_KEY` | Google Fact Check Tools API (optional, falls back to `GEMMA_API_KEY`) |
| `FACTCHECK_AGENT_SEED` | Stable seed phrase for deterministic agent address |
| `FACTCHECK_AGENT_ADDRESS` | The `agent1q...` address printed on first agent run |
| `AGENTVERSE_MAILBOX_KEY` | JWT from agentverse.ai for auto-registration (optional) |
| `HOST`, `PORT` | Backend bind address (default `0.0.0.0:8787`) |

## Repo Layout

```
veritas/
├── backend/                      # FastAPI service (Python)
│   └── app/
│       ├── main.py
│       ├── config.py             # pydantic-settings
│       ├── ws/                   # WebSocket endpoints
│       ├── pipeline/             # orchestrator, claim extraction, verdict prompts, chat
│       ├── agents/               # uAgent + client (Fetch.ai)
│       ├── rag/                  # SQLite vector cache
│       └── adapters/             # Gemma LLM, Gemini embeddings, Wikipedia, Google Fact Check
├── extension/                    # Chrome MV3 extension (vanilla JS, no build step)
│   ├── manifest.json
│   ├── background/               # service worker — WS management
│   ├── content/                  # YouTube caption observer + overlay UI + chat
│   ├── overlay/                  # CSS theme
│   ├── popup/                    # toolbar popup
│   └── lib/                      # config, message types
├── scripts/                      # dev scripts, smoke tests
├── PLAN.md                       # original design doc
└── DEVPOST.md                    # hackathon submission write-up
```

## Built With

Python, JavaScript, FastAPI, Google Gemma, Google Gemini, Fetch.ai uAgents, Agentverse, Chrome Extensions (MV3), SQLite, Wikipedia API, Google Fact Check Tools API, WebSockets, Pydantic
