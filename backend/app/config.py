from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemma_api_key: str = ""
    tavily_api_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8787
    allowed_origins: str = "*"

    # Pipeline tuning
    claim_min_chars: int = 40
    # How often (seconds) the analyzer drains the transcript buffer and makes
    # ONE LLM call covering all text accumulated since the last call.
    analyze_interval_seconds: float = 20.0
    # Hard floor between consecutive LLM calls; backoff doubles this on 429.
    min_llm_interval_seconds: float = 12.0
    # Skip a window if it has fewer than this many chars (avoids wasting calls
    # on near-empty buffers).
    min_chunk_chars: int = 80
    # Text model for claim extraction + verdict judging.
    # Default is gemini-2.0-flash (has a free tier); override to a Gemma model
    # via env if you have prepaid credits, e.g. VERDICT_MODEL=gemma-3-27b-it.
    verdict_model: str = "gemini-2.0-flash"
    # Audio transcription model (multimodal). Same Google API key.
    asr_model: str = "gemini-2.0-flash"

    @property
    def has_llm(self) -> bool:
        return bool(self.gemma_api_key)

    @property
    def has_tavily(self) -> bool:
        return bool(self.tavily_api_key)


settings = Settings()
