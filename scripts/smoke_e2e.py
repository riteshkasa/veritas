#!/usr/bin/env python3
"""End-to-end smoke test: pretend to be the extension, push CC cues over WS,
print everything the backend streams back. Both the backend and the fact-check
agent must be running.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import websockets  # noqa: E402

WS = "ws://127.0.0.1:8787/ingest/captions"


async def main() -> int:
    transcript = (
        "The Eiffel Tower is 330 meters tall including its antennas. "
        "It was completed in 1889 for the Paris World's Fair. "
        "Gustave Eiffel's company built the tower."
    )
    cue_chunks = [s.strip() + "." for s in transcript.split(".") if s.strip()]

    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({"type": "hello", "sessionId": "smoke", "videoId": "test"}))
        for i, text in enumerate(cue_chunks):
            await ws.send(json.dumps({
                "type": "cue",
                "sessionId": "smoke",
                "videoId": "test",
                "startMs": 1000 * i,
                "endMs": 1000 * (i + 1),
                "text": text,
            }))
            print(f">> cue: {text!r}")
            await asyncio.sleep(0.2)
        await ws.send(json.dumps({"type": "flush"}))

        # Read responses for ~30s.
        try:
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                msg = json.loads(raw)
                t = msg.get("type")
                if t == "verdict":
                    cites = msg.get("citations") or []
                    print(f"<< VERDICT: {msg['verdict']} ({msg['confidence']:.2f}) — {msg['claim']}")
                    print(f"   rationale: {msg.get('rationale','')[:140]}")
                    for c in cites:
                        print(f"   [{c.get('title')}] {c.get('url')}")
                elif t == "transcript":
                    print(f"<< transcript: {msg['text'][:80]!r}")
                elif t == "status":
                    print(f"<< status [{msg.get('level','info')}]: {msg.get('message','')}")
                else:
                    print(f"<< {t}: {msg}")
        except asyncio.TimeoutError:
            print("(no more messages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
