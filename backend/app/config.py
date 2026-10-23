"""Application configuration.

Secrets are read from environment variables / a local `.env` file that is
never committed. Placeholders live in `.env.example`.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Acquisitions Assistant AI"
    environment: str = "local"
    host: str = "127.0.0.1"
    port: int = 8000
    database_url: str = f"sqlite:///{BASE_DIR / 'acquisitions.db'}"
    timezone: str = "America/New_York"

    # --- REsimpli Open API v6 -------------------------------------------------
    # Docs: https://developer.resimpli.com
    # Auth header:  Authorization: <API_KEY>   (raw key, no Bearer prefix)
    resimpli_api_key: str = ""
    resimpli_base_url: str = "https://api.resimpli.com/api/v6/openapi"
    resimpli_timeout_seconds: float = 30.0
    # Conservative default. Help centre states 500 req/min (raised from 100 on
    # 2026-10-01); the embedded developer portal still documents 100 req/min.
    resimpli_rate_limit_per_minute: int = 100
    resimpli_max_retries: int = 4
    # Force the mock client even when a key is configured.
    resimpli_mock: bool = False
    # Sync tuning
    sync_enabled: bool = False
    sync_interval_minutes: int = 30
    sync_page_limit: int = 100
    sync_max_pages: int = 500
    # Number of leads per run that get the (expensive) /lead/details + activity
    # enrichment. 0 disables enrichment entirely.
    sync_detail_budget: int = 250

    # --- Optional local AI (Ollama) -------------------------------------------
    ai_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"
    # CPU-only machines routinely fail to allocate Ollama's default 8k-context
    # KV cache (HTTP 500, "failed to allocate buffer of size 8589934592").
    # 2048 tokens fits comfortably and keeps prompts inside the window.
    ollama_num_ctx: int = 2048
    ollama_timeout_seconds: float = 90.0
    # After a generation failure the model is skipped for this many seconds so
    # the UI keeps responding instead of stalling on every analysis.
    ollama_failure_cooldown_seconds: int = 120

    # --- Groq cloud AI (OpenAI-compatible, https://console.groq.com) ----------
    # When a key is set, Groq is the primary engine and Ollama becomes the
    # fallback. Key lives only in backend/.env (never committed).
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_timeout_seconds: float = 30.0
    # Free-tier ceiling is 8000 tokens/min (~3-4 analyses). Pacing batch runs
    # this far apart keeps them under the limit instead of riding HTTP 429s.
    groq_batch_spacing_seconds: float = 16.0

    # --- Misc -----------------------------------------------------------------
    upload_dir: str = str(BASE_DIR / "uploads")
    max_upload_mb: int = 50
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
