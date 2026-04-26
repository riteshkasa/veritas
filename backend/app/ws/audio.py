"""WebSocket endpoint for streamed audio segments.

Wire protocol (per segment):
  1. JSON text frame: {"type":"segment-meta","videoTimeMs":int,"mime":str}
  2. Binary frame:    raw bytes of the self-contained audio segment

A leading {"type":"hello", sessionId, videoId} frame initializes the session.
A {"type":"flush"} frame (optional) drains any buffered orchestrator state.
"""
import json
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.adapters.asr.groq_whisper import transcribe
from app.config import settings
from app.pipeline.orchestrator import Session
from app.pipeline.schemas import StatusOut, TranscriptOut
from app.utils.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.websocket("/ingest/audio")
async def audio_ws(ws: WebSocket) -> None:
    await ws.accept()
    log.info("audio WS: accepted, groq_configured=%s", bool(settings.groq_api_key))

    session: Session | None = None
    pending_meta: dict | None = None
    seg_count = 0
    total_bytes = 0

    async def send(payload: dict) -> None:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            pass

    if not settings.groq_api_key:
        await send(StatusOut(
            level="warn",
            message="Audio Path: GROQ_API_KEY Not Set — Transcripts Will Be Empty",
        ).model_dump())

    try:
        while True:
            msg = await ws.receive()
            mtype_raw = msg.get("type")
            if mtype_raw == "websocket.disconnect":
                log.info("audio WS: disconnect frame; segments=%d total_bytes=%d", seg_count, total_bytes)
                break

            if "text" in msg and msg["text"] is not None:
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    log.warning("audio WS: bad json text frame: %r", msg["text"][:120])
                    continue
                mtype = data.get("type")
                log.info("audio WS: text frame type=%s keys=%s", mtype, list(data.keys()))

                if mtype == "hello":
                    session = Session(
                        session_id=data.get("sessionId") or "anon",
                        video_id=data.get("videoId") or "",
                        send=send,
                    )
                    log.info("audio WS: hello -> session %s video=%s",
                             session.session_id, session.video_id)
                    continue

                if mtype == "segment-meta":
                    pending_meta = data
                    log.info("audio WS: segment-meta videoTimeMs=%s mime=%s",
                             data.get("videoTimeMs"), data.get("mime"))
                    continue

                if mtype == "flush":
                    if session:
                        await session.flush()
                    continue

            elif "bytes" in msg and msg["bytes"] is not None:
                audio = msg["bytes"]
                seg_count += 1
                total_bytes += len(audio)
                meta = pending_meta or {}
                pending_meta = None
                log.info("audio WS: binary frame #%d bytes=%d (meta_present=%s)",
                         seg_count, len(audio), bool(meta))
                if session is None:
                    log.warning("audio WS: dropping segment, no session yet (missing hello?)")
                    continue
                video_time_ms = int(meta.get("videoTimeMs") or 0)
                mime = meta.get("mime") or "audio/webm"

                t0 = time.time()
                transcript = await transcribe(audio, mime=mime)
                dt = time.time() - t0
                log.info("audio WS: groq returned in %.2fs len=%d preview=%r",
                         dt, len(transcript), transcript[:80])

                if not transcript:
                    await send(TranscriptOut(text="…", video_time_ms=video_time_ms).model_dump())
                    continue
                await session.feed(transcript, video_time_ms)
            else:
                log.info("audio WS: unknown frame shape keys=%s", list(msg.keys()))

    except WebSocketDisconnect:
        log.info("audio WS: WebSocketDisconnect; segments=%d total_bytes=%d", seg_count, total_bytes)
    except Exception as e:
        log.exception("audio WS error: %s", e)
    finally:
        if session is not None:
            await session.close()
