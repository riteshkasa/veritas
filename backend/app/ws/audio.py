import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.adapters.asr.gemini_asr import transcribe
from app.config import settings
from app.pipeline.orchestrator import Session
from app.pipeline.schemas import StatusOut, TranscriptOut
from app.utils.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.websocket("/ingest/audio")
async def ingest_audio(ws: WebSocket) -> None:
    """Protocol:
      1) Client -> JSON {type: 'hello', sessionId, videoId, codec, sampleRate, mime}
      2) For each segment:
           Client -> JSON {type: 'segment_meta', videoTimeMs, mime}
           Client -> binary frame (one self-contained audio file, e.g. webm/opus)
      3) Client may send {type:'flush'} on close.
    """
    await ws.accept()
    session: Session | None = None
    pending_meta: dict | None = None
    default_mime = "audio/webm"

    async def send(payload: dict) -> None:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            pass

    if not settings.has_llm:
        await send(
            StatusOut(
                message="audio path: no GEMMA_API_KEY set; transcripts will be empty",
                level="warn",
            ).model_dump()
        )

    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            text = msg.get("text")
            data_bytes = msg.get("bytes")

            if text is not None:
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    await send(StatusOut(message="invalid json", level="warn").model_dump())
                    continue

                mtype = data.get("type")
                if mtype == "hello":
                    session = Session(
                        session_id=data.get("sessionId", "anon"),
                        video_id=data.get("videoId", ""),
                        send=send,
                    )
                    default_mime = data.get("mime", default_mime)
                    await send(StatusOut(message="audio session ready").model_dump())
                elif mtype == "segment_meta":
                    pending_meta = data
                elif mtype == "flush":
                    if session:
                        await session.flush()
                else:
                    await send(StatusOut(message=f"unknown type {mtype}", level="warn").model_dump())

            elif data_bytes is not None:
                if session is None:
                    await send(StatusOut(message="binary before hello", level="warn").model_dump())
                    continue
                meta = pending_meta or {}
                pending_meta = None
                video_time_ms = int(meta.get("videoTimeMs", 0))
                mime = meta.get("mime", default_mime)

                transcript = await transcribe(data_bytes, mime=mime)
                if not transcript:
                    await send(
                        TranscriptOut(text="…", video_time_ms=video_time_ms).model_dump()
                    )
                    continue
                await session.feed(transcript, video_time_ms)

    except WebSocketDisconnect:
        log.info("audio WS disconnected")
    except Exception as e:
        log.exception("audio WS error: %s", e)
    finally:
        if session is not None:
            await session.close()
