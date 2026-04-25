# Niwas — Real-Time Video Fact Checker

A Chrome extension that fact-checks whatever video is playing on screen (YouTube first) in real time and overlays the results. It prefers the video's closed captions when available; otherwise it captures the tab's audio in chunks, transcribes them, and runs claim detection + retrieval-augmented fact checking.

---

## 1. Goals & Non-Goals

### Goals
- **Real-time-ish**: target < ~5s from spoken claim to on-screen verdict.
- **Source-aware ingestion**: use CC track if present (cheap, accurate); fall back to tab-audio capture + ASR.
- **Transparent verdicts**: each claim shows verdict (`true` / `false` / `misleading` / `unverified`), confidence, and citations (URL + snippet).
- **Non-intrusive UI**: draggable side panel + inline timeline markers synced to the video.
- **YouTube-first**, but architected so other sites (Twitch, generic `<video>`) drop in later.

### Non-Goals (for hackathon)
- Mobile / Safari / Firefox.
- Fact-checking visual content (charts, on-screen text) — text-from-speech only for v1.
- Multi-language; English first.

---

## 2. High-Level Architecture

```
+-----------------------------+          WS / HTTP          +------------------------------+
|   Chrome Extension (MV3)    | <-------------------------> |   Backend (FastAPI, Python)  |
|                             |                             |                              |
|  - content script (YT)      |  captions OR audio chunks   |  /ingest/captions  (WS)      |
|  - background service worker|  ------------------------>  |  /ingest/audio     (WS)      |
|  - offscreen document       |                             |    -> Gemini multimodal ASR  |
|    (tabCapture -> PCM/Opus) |     verdicts + citations    |  Claim segmenter (LLM)       |
|  - overlay UI (React)       |  <------------------------- |  Retriever (Tavily/Brave +   |
|                             |                             |    Wikipedia + News API)     |
|                             |                             |  Verdict LLM (Gemma)         |
|                             |                             |  Redis cache (claim->verdict)|
+-----------------------------+                             +------------------------------+
```

### End-to-End Flow
1. **Detect video** — content script finds the active `<video>` on YouTube.
2. **Caption path (preferred)** — read the active caption track from YouTube's player API; stream cue text + timestamps to backend over WebSocket.
3. **Audio fallback** — if no CC, background SW opens an offscreen document that calls `chrome.tabCapture` to get a `MediaStream`, encodes ~3s Opus/PCM chunks, and streams them over WebSocket; backend runs streaming ASR.
4. **Claim segmentation** — backend buffers transcript, splits into check-worthy claims (LLM with a cheap classifier prefilter).
5. **Retrieval** — for each claim, fetch top-k web results + Wikipedia snippets.
6. **Verdict** — LLM judges claim against retrieved evidence; returns `{verdict, confidence, citations[], rationale}`.
7. **Render** — extension overlays card in side panel and drops a marker on the video progress bar at the claim's timestamp.

---

## 3. Tech Stack

- **Extension**: Manifest V3, TypeScript, React + Vite, Tailwind, shadcn/ui, Lucide icons.
- **Audio**: `chrome.tabCapture` in an offscreen document, `MediaRecorder` (Opus) or `AudioWorklet` (PCM16 @ 16kHz).
- **Transport**: WebSocket (binary frames for audio, JSON for captions/verdicts).
- **Backend**: Python 3.11, FastAPI, Uvicorn, `websockets`.
- **ASR**: Gemini multimodal `generateContent` (audio inline_data) via the Google Generative Language API.
- **LLM**: Gemma (default `gemma-3-27b-it`) for claim segmentation + verdict judging via the same Google API.
- **Search**: Tavily or Brave Search API; Wikipedia REST; optional NewsAPI.
- **Cache**: Redis (claim hash -> verdict, 24h TTL).
- **Infra**: Docker Compose for local; deploy backend to Fly.io/Render for demo.

---

## 4. Directory Structure

```
niwas/
├── PLAN.md
├── README.md
├── .gitignore
├── .env.example
├── docker-compose.yml
│
├── extension/                          # Chrome MV3 extension
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── public/
│   │   ├── manifest.json
│   │   └── icons/
│   │       ├── icon16.png
│   │       ├── icon48.png
│   │       └── icon128.png
│   └── src/
│       ├── background/
│       │   └── service-worker.ts       # routes messages, manages WS, opens offscreen doc
│       ├── offscreen/
│       │   ├── offscreen.html
│       │   └── offscreen.ts            # tabCapture + audio encoding
│       ├── content/
│       │   ├── index.ts                # entry; detects YT video
│       │   ├── youtube.ts               # caption track reader, timeline hooks
│       │   ├── video-detector.ts       # generic <video> fallback
│       │   └── overlay-mount.tsx       # injects React root into the page
│       ├── overlay/                    # React UI shown over the video
│       │   ├── App.tsx
│       │   ├── components/
│       │   │   ├── SidePanel.tsx
│       │   │   ├── VerdictCard.tsx
│       │   │   ├── TimelineMarkers.tsx
│       │   │   └── StatusPill.tsx
│       │   ├── hooks/
│       │   │   ├── useVerdictStream.ts
│       │   │   └── useVideoTime.ts
│       │   └── styles.css
│       ├── popup/                      # toolbar popup (on/off, settings)
│       │   ├── popup.html
│       │   ├── Popup.tsx
│       │   └── popup.ts
│       ├── lib/
│       │   ├── ws-client.ts            # reconnecting WS wrapper
│       │   ├── audio-encoder.ts        # PCM16/Opus framing
│       │   ├── captions/
│       │   │   ├── youtube-cc.ts       # parse timedtext XML/JSON3
│       │   │   └── types.ts
│       │   ├── messages.ts             # typed cross-context messages
│       │   └── storage.ts              # chrome.storage helpers
│       └── types/
│           └── index.ts
│
├── backend/                            # FastAPI service
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── README.md
│   └── app/
│       ├── main.py                     # FastAPI app + WS routes
│       ├── config.py                   # env settings (pydantic-settings)
│       ├── ws/
│       │   ├── captions.py             # /ingest/captions
│       │   └── audio.py                # /ingest/audio
│       ├── pipeline/
│       │   ├── orchestrator.py         # per-session state machine
│       │   ├── transcript_buffer.py    # rolling window, sentence assembly
│       │   ├── claim_segmenter.py      # LLM-based check-worthy claim extraction
│       │   ├── retriever.py            # web + wiki search
│       │   ├── verdict.py              # LLM judge with evidence
│       │   └── schemas.py              # pydantic models (Claim, Verdict, Evidence)
│       ├── adapters/
│       │   ├── asr/
│       │   │   ├── base.py
│       │   │   └── gemini_asr.py
│       │   ├── llm/
│       │   │   ├── base.py
│       │   │   └── gemma_client.py
│       │   └── search/
│       │       ├── base.py
│       │       ├── tavily.py
│       │       ├── brave.py
│       │       └── wikipedia.py
│       ├── cache/
│       │   └── redis_cache.py
│       └── utils/
│           ├── logging.py
│           └── hashing.py
│
├── shared/                             # shared JSON schemas / types
│   └── schemas/
│       ├── verdict.schema.json
│       └── claim.schema.json
│
├── scripts/
│   ├── dev-backend.sh
│   ├── dev-extension.sh
│   └── load-extension-instructions.md
│
└── tests/
    ├── extension/
    │   ├── youtube-cc.test.ts
    │   └── audio-encoder.test.ts
    └── backend/
        ├── test_claim_segmenter.py
        ├── test_retriever.py
        └── test_verdict.py
```

---

## 5. Key Interfaces

### WebSocket: `/ingest/captions`
Client -> server (JSON):
```json
{ "type": "cue", "sessionId": "uuid", "videoId": "yt:abc123",
  "startMs": 12340, "endMs": 14120, "text": "The Eiffel Tower is 1000 feet tall." }
```

### WebSocket: `/ingest/audio`
- First frame: JSON `{ "type": "hello", "sessionId", "videoId", "codec": "opus|pcm16", "sampleRate": 16000 }`
- Subsequent frames: binary audio chunks (~1–3s).

### Server -> client (either route):
```json
{ "type": "verdict", "claimId": "c_01H..", "videoTimeMs": 12340,
  "claim": "The Eiffel Tower is 1000 feet tall.",
  "verdict": "false", "confidence": 0.92,
  "rationale": "Actual height is ~1083 ft including antenna; the claim's framing is misleading.",
  "citations": [
    { "title": "Eiffel Tower - Wikipedia", "url": "https://en.wikipedia.org/wiki/Eiffel_Tower", "snippet": "..." }
  ] }
```

---

## 6. Milestones (Hackathon Cut)

1. **M0 — Skeleton (1–2h)**: repo scaffolding, manifest, FastAPI hello, WS echo.
2. **M1 — Captions path (2–3h)**: read YT caption cues, stream to backend, return mocked verdicts, render side panel.
3. **M2 — Verdict pipeline (3–4h)**: claim segmenter + retriever + verdict LLM with real APIs, Redis cache.
4. **M3 — Audio fallback (3–4h)**: offscreen `tabCapture`, Opus chunking, Gemini multimodal ASR.
5. **M4 — Polish (2h)**: timeline markers, confidence styling, popup toggle, demo video.

## 7. Risks & Mitigations
- **YT caption access is brittle** → keep audio fallback first-class.
- **LLM latency** → parallelize retrieval; pick a fast Gemma variant; cache aggressively by claim hash.
- **`tabCapture` quirks in MV3** → must use offscreen document; tested early in M0.
- **Hallucinated citations** → verdict prompt must cite only from supplied evidence; reject otherwise.

## 8. Env Vars (`.env.example`)
```
GEMMA_API_KEY=
TAVILY_API_KEY=
BRAVE_API_KEY=
REDIS_URL=redis://localhost:6379/0
ALLOWED_ORIGINS=chrome-extension://*
```
