"""Secret storage with Windows Credential Manager first, .env.secrets as fallback.

Phase 1.3 of the 1.4.0 plan. Keys are never returned in full by any endpoint.
"""

from __future__ import annotations

import re

SECRET_NAME = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


SERVICE_NAME = "AcquisitionsAssistant"

try:
    import keyring as _keyring

    _HAS_KEYRING = True
except Exception:  # pragma: no cover - depends on platform
    _keyring = None
    _HAS_KEYRING = False


def has_keyring() -> bool:
    return _HAS_KEYRING


def get_secret(key: str) -> str | None:
    if _HAS_KEYRING:
        try:
            value = _keyring.get_password(SERVICE_NAME, key)
            if value:
                return value
        except Exception:
            pass
    # Fallback: .env.secrets (private_settings)
    from .. import config

    try:
        from dotenv import dotenv_values

        path = config.private_settings_path()
        if path.exists():
            return dotenv_values(path).get(key)
    except Exception:
        pass
    return None


def set_secret(key: str, value: str | None) -> None:
    if _HAS_KEYRING:
        try:
            if value is None:
                _keyring.delete_password(SERVICE_NAME, key)
            else:
                _keyring.set_password(SERVICE_NAME, key, value)
            return
        except Exception:
            pass
    # Fallback
    from . import private_settings

    private_settings.write_secret({key: value})


def migrate_env_to_secrets() -> dict:
    """One-time: move API keys from .env into the secret store. Returns what moved."""
    from .. import config

    moved = {}
    env_path = config.DATA_ROOT / ".env"
    if not env_path.exists():
        return moved
    try:
        from dotenv import dotenv_values

        values = dotenv_values(env_path)
    except Exception:
        return moved
    for key in ("RESIMPLI_API_KEY", "GROQ_API_KEY"):
        val = values.get(key)
        if val and val.strip():
            if get_secret(key) is None:
                set_secret(key, val.strip())
                moved[key] = "migrated"
    # marker
    marker = config.DATA_ROOT / ".secrets_migrated"
    if moved and not marker.exists():
        marker.write_text("1", encoding="utf-8")
    return moved


def storage_backend() -> str:
    return "keyring" if _HAS_KEYRING else "env.secrets (fallback)"
