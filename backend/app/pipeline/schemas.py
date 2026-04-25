from typing import Literal, List, Optional
from pydantic import BaseModel, Field


Verdict = Literal["true", "false", "misleading", "unverified"]


class Citation(BaseModel):
    title: str
    url: str
    snippet: str = ""


class Claim(BaseModel):
    claim_id: str
    text: str
    video_time_ms: int = 0
    session_id: str = ""
    video_id: str = ""


class VerdictResult(BaseModel):
    type: Literal["verdict"] = "verdict"
    claim_id: str
    video_time_ms: int
    claim: str
    verdict: Verdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""
    citations: List[Citation] = []


class CueIn(BaseModel):
    type: Literal["cue"]
    session_id: str = Field(alias="sessionId")
    video_id: str = Field(alias="videoId")
    start_ms: int = Field(alias="startMs")
    end_ms: int = Field(alias="endMs")
    text: str

    model_config = {"populate_by_name": True}


class HelloAudio(BaseModel):
    type: Literal["hello"]
    session_id: str = Field(alias="sessionId")
    video_id: str = Field(alias="videoId")
    codec: Literal["opus", "pcm16", "webm"] = "webm"
    sample_rate: int = Field(default=48000, alias="sampleRate")

    model_config = {"populate_by_name": True}


class StatusOut(BaseModel):
    type: Literal["status"] = "status"
    message: str
    level: Literal["info", "warn", "error"] = "info"


class TranscriptOut(BaseModel):
    type: Literal["transcript"] = "transcript"
    text: str
    video_time_ms: Optional[int] = None
