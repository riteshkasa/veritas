from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve `.env` relative to the backend dir so it works no matter what
# CWD a script is run from.
_ENV_FILE = str(Path(__file__).resolve().parent.parent / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    gemma_api_key: str = ""
    tavily_api_key: str = ""
    google_factcheck_api_key: str = ""
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
    verdict_model: str = "gemma-3-27b-it"
    embedding_model: str = "gemini-embedding-001"

    # RAG cache
    cache_db_path: str = "./cache.db"
    # Cosine similarity threshold for returning a cached verdict instead of
    # re-fetching evidence. Deliberately high to avoid stale hits.
    cache_sim_threshold: float = 0.85

    # Fact-check uAgent
    factcheck_agent_seed: str = ""
    factcheck_agent_address: str = ""
    factcheck_agent_endpoint: str = "http://127.0.0.1:8001/submit"
    factcheck_timeout_seconds: float = 20.0
    # Agentverse Mailbox API key (JWT). If set, the agent registers with
    # Agentverse using this key instead of relying on the inspector UI flow.
    agentverse_mailbox_key: str = ""

    @property
    def has_llm(self) -> bool:
        return bool(self.gemma_api_key)

    @property
    def has_tavily(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def factcheck_key(self) -> str:
        # Fact Check Tools and Gemini share a Google API key. Prefer the
        # dedicated one if set, fall back to the Gemma key.
        return self.google_factcheck_api_key or self.gemma_api_key


settings = Settings()
