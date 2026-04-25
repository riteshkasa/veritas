from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.utils.logging import setup_logging
from app.ws.captions import router as captions_router
from app.ws.audio import router as audio_router


setup_logging()
app = FastAPI(title="Niwas Fact Checker", version="0.1.0")

origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "gemma": settings.has_llm,
        "tavily": settings.has_tavily,
        "verdict_model": settings.verdict_model,
        "asr_model": settings.asr_model,
    }


app.include_router(captions_router)
app.include_router(audio_router)


def main() -> None:
    import uvicorn

    import os

    reload = os.getenv("NIWAS_NO_RELOAD") != "1"
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=reload,
        reload_dirs=["app"] if reload else None,
    )


if __name__ == "__main__":
    main()
