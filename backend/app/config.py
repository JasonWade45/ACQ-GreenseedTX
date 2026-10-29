from pathlib import Path
import os
from functools import lru_cache
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo
from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from .paths import data_root, resource_root

# Read-only build files (interface, migrations, fixtures).
ROOT = resource_root()
# The person's own files (database, password, backups). Separate on purpose: an
# update replaces the build, never the data.
DATA_ROOT = data_root()


PSQL_INSECURE_MODES = {"disable", "allow", "prefer"}
PSQL_SECURE_MODES = {"require", "verify-ca", "verify-full"}
LOCAL_DB_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def normalise_database_url(value: str) -> str:
    """Return a SQLAlchemy URL, accepting the plain URLs hosted providers hand out.

    A hosted PostgreSQL database is never reached without TLS: an explicit
    ``sslmode`` of require/verify-ca/verify-full is mandatory unless the server is on
    this machine (a unix socket or loopback), where there is nothing to intercept.
    """
    url = (value or "").strip()
    if not url:
        return ""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix) :]
            break
    if not url.startswith("postgresql"):
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)
    mode = (query.get("sslmode") or [""])[0].lower()
    if host in LOCAL_DB_HOSTS:
        return url
    if mode not in PSQL_SECURE_MODES:
        raise ValueError(
            "A hosted PostgreSQL database requires sslmode=require (or verify-ca/verify-full) "
            f"in DATABASE_URL; got sslmode={mode or 'missing'!r} for host {host!r}"
        )
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=DATA_ROOT / ".env", extra="ignore")
    # Filled in below so a moved data folder is honoured without re-importing.
    database_url: str = ""
    # Hosted PostgreSQL only: the exact browser origin of a separately deployed
    # interface. Never "*": a wildcard would let any page on the internet drive an
    # authenticated session. Comma-separated when more than one origin is needed.
    cors_origins: str = ""
    # Shared secret for the external cron trigger of the daily cadence runner.
    cron_secret: str = ""
    # Long-lived in-process scheduler for sync/backup/cadence. On a host whose
    # process is suspended (serverless, free tiers) turn this off and use the cron
    # endpoint instead.
    scheduler_enabled: bool = True
    # Hosted filesystems are ephemeral. When set, backups are still written but are
    # reported as non-durable so the interface asks for a download instead.
    ephemeral_filesystem: bool = False
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
    # Where backups go when the database is not a file (PostgreSQL). Empty means the
    # data folder; on a host that wipes its filesystem, point this at a mounted volume.
    backup_dir: str = ""
    backup_keep: int = Field(default=7, ge=1, le=90)
    backup_hour_utc: int = Field(default=2, ge=0, le=23)
    # Daily cadence runner: prepares the follow-up drafts that are due today.
    cadence_enabled: bool = True
    cadence_hour_utc: int = Field(default=12, ge=0, le=23)
    # Appended verbatim to every reviewed draft. Never printed in status endpoints.
    draft_signature: str = "Jason Wade\nAcquisition Manager, GreenSeedTX LLC"
    draft_manager_name: str = "Jason Wade"
    draft_company: str = "GreenSeedTX LLC"
    # Opener identity used by every draft path (relationship and cold). Configurable
    # in Settings; a cold draft refuses to render when either value is blank.
    sender_name: str = "Jason Wade"
    company_name: str = "GreenSeedTX LLC"

    @field_validator("sender_name", "company_name")
    @classmethod
    def identity_values(cls, value):
        text = (value or "").strip()
        if not text or len(text) > 120 or "\n" in text or "\r" in text:
            raise ValueError("Sender name and company must be one line of at most 120 characters")
        return text

    @field_validator("database_url")
    @classmethod
    def default_database(cls, value):
        return normalise_database_url(value) or f"sqlite:///{DATA_ROOT / 'data/acquisitions.db'}"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip().rstrip("/") for item in self.cors_origins.split(",") if item.strip()]

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
    path = Path(os.environ.get("APP_PRIVATE_SETTINGS_PATH", str(DATA_ROOT / ".env.secrets"))).expanduser()
    return path if path.is_absolute() else DATA_ROOT / path


@lru_cache
def get_settings():
    return Settings(_env_file=(DATA_ROOT / ".env", private_settings_path()))
