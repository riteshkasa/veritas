import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.pipeline.orchestrator import Session
from app.pipeline.schemas import CueIn, StatusOut
from app.utils.logging import get_logger

log = get_logger(__name__)
router = APIRouter()


@router.websocket("/ingest/captions")
async def ingest_captions(ws: WebSocket) -> None:
    await ws.accept()
    session: Session | None = None

    async def send(payload: dict) -> None:
        try:
            await ws.send_text(json.dumps(payload))
        except Exception:
            pass

    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                await send(StatusOut(message="Invalid JSON", level="warn").model_dump())
                continue

            mtype = data.get("type")
            if mtype == "hello":
                session = Session(
                    session_id=data.get("sessionId", "anon"),
                    video_id=data.get("videoId", ""),
                    send=send,
                    video_meta=data.get("meta") or {},
                )
                await send(StatusOut(message="Veritas Online").model_dump())
                continue

            if mtype == "cue":
                if session is None:
                    session = Session(
                        session_id=data.get("sessionId", "anon"),
                        video_id=data.get("videoId", ""),
                        send=send,
                        video_meta=data.get("meta") or {},
                    )
                try:
                    cue = CueIn.model_validate(data)
                except Exception as e:
                    await send(StatusOut(message=f"Bad Cue: {e}", level="warn").model_dump())
                    continue
                await session.feed(cue.text, cue.start_ms)
                continue

            if mtype == "flush":
                if session:
                    await session.flush()
                continue

    except WebSocketDisconnect:
        log.info("captions WS disconnected")
    except Exception as e:
        log.exception("captions WS error: %s", e)
    finally:
        if session is not None:
            await session.close()
