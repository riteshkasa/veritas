# Niwas — Real-Time Video Fact Checker

A Chrome extension + FastAPI backend that fact-checks YouTube videos in real time. It prefers the video's closed captions when available; otherwise it captures the tab's audio in chunks, transcribes via Gemini, segments check-worthy claims with Gemma, retrieves evidence (Wikipedia + optional Tavily web search), and overlays verdicts on the video.

See `PLAN.md` for the full design.

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env   # optional; without keys the pipeline runs in mock mode
python -m app.main
```

Health check: `curl http://localhost:8787/health`

### 2. Chrome extension

1. Open `chrome://extensions` and enable **Developer mode**.
2. Click **Load unpacked** and pick the `extension/` folder.
3. Open any YouTube video. A draggable **Niwas Fact Check** panel appears.
4. Click **Start**. It tries captions first, then falls back to tab audio after 6 s if no captions are detected.

See `scripts/load-extension-instructions.md` for more.

## Repo layout

```
niwas/
├── PLAN.md                       # design doc
├── backend/                      # FastAPI service (Python)
│   └── app/
│       ├── main.py
│       ├── ws/                   # /ingest/captions and /ingest/audio
│       ├── pipeline/             # buffer → claim seg → retrieve → verdict
│       └── adapters/             # Gemma (LLM), Gemini (ASR), Wikipedia, Tavily
├── extension/                    # Chrome MV3 extension (vanilla JS, no build)
│   ├── manifest.json
│   ├── background/service-worker.js
│   ├── offscreen/                # tabCapture + MediaRecorder
│   ├── content/content.js        # YouTube CC observer + overlay UI
│   ├── overlay/overlay.css
│   ├── popup/
│   └── lib/
└── scripts/
```

## Modes of operation

- **Captions mode** — content script observes `.ytp-caption-segment` mutations and streams cues over a WebSocket.
- **Audio mode** — service worker creates an offscreen document that calls `chrome.tabCapture` and posts ~5 s Opus segments to the backend, which transcribes via a Gemini multimodal model.

## Configuration

Set in `backend/.env` (or copy `.env.example`):

| Var | Purpose |
| --- | --- |
| `GEMMA_API_KEY`  | Google API key — Gemma for text (claims + verdicts), Gemini for audio ASR |
| `TAVILY_API_KEY` | Optional web search retrieval (Wikipedia is always on) |
| `HOST`, `PORT`  | Backend bind address (default `0.0.0.0:8787`) |

To point the extension at a non-local backend, edit `extension/lib/config.js`.

## Status

v0.1 — first working slice. Known limitations:

- YouTube only.
- English only.
- No persistence; verdicts live in memory per session.
- Audio segments are 5 s blocks (not streaming ASR), so audio-mode latency is ~6–10 s.
