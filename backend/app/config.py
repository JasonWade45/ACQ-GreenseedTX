from pathlib import Path
import os
from functools import lru_cache
from zoneinfo import ZoneInfo
from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")
    database_url: str = f"sqlite:///{ROOT / 'data/acquisitions.db'}"
    app_timezone: str = "America/New_York"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_access_password: str = ""
    session_secret: str = ""
    resimpli_api_key: str = Field(default="", repr=False)
    resimpli_mode: str = "disabled"
    resimpli_adapter_path: str = ""
    resimpli_adapter_verified: bool = False
    sync_enabled: bool = False
    sync_interval_minutes: int = 30
    sync_requests_per_minute: int = 90
    sync_max_pages: int = 1000
    sync_deep_refresh_hours: int = 24
    ollama_enabled: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = ""
    groq_enabled: bool = False
    groq_api_key: str = Field(default="", repr=False)
    groq_model: str = "openai/gpt-oss-20b"
    groq_daily_request_limit: int = Field(default=30, ge=1, le=500)
    groq_max_output_tokens: int = Field(default=3000, ge=512, le=4096)
    max_upload_mb: int = 25
    max_import_rows: int = 50000
    backup_enabled: bool = True
    backup_keep: int = Field(default=7, ge=1, le=90)
    backup_hour_utc: int = Field(default=2, ge=0, le=23)
    # Appended verbatim to every reviewed draft. Never printed in status endpoints.
    draft_signature: str = "Jason Wade\nAcquisition Manager, GreenSeedTX LLC"
    draft_manager_name: str = "Jason Wade"
    draft_company: str = "GreenSeedTX LLC"

    @field_validator("app_timezone")
    @classmethod
    def valid_timezone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator("resimpli_mode")
    @classmethod
    def mode(cls, value):
        if value not in {"disabled", "fixture", "live"}:
            raise ValueError("Use disabled, fixture or live")
        return value

    @field_validator("sync_interval_minutes")
    @classmethod
    def interval(cls, value):
        if not 1 <= value <= 10080:
            raise ValueError("Interval must be 1–10080 minutes")
        return value


def private_settings_path():
    path = Path(os.environ.get("APP_PRIVATE_SETTINGS_PATH", str(ROOT / ".env.secrets"))).expanduser()
    return path if path.is_absolute() else ROOT / path


@lru_cache
def get_settings():
    return Settings(_env_file=(ROOT / ".env", private_settings_path()))
