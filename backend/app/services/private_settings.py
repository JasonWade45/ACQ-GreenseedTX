"""Backend-only private settings. No secret value is returned, audited or logged."""

import json
import os
import re
from pathlib import Path
import tempfile
import threading
from dotenv import dotenv_values
from .. import config

LOCK = threading.Lock()
ALLOWED = {
    "GROQ_API_KEY",
    "GROQ_ENABLED",
    "GROQ_MODEL",
    "GROQ_DAILY_REQUEST_LIMIT",
    "GROQ_MAX_OUTPUT_TOKENS",
    "RESIMPLI_API_KEY",
    "RESIMPLI_MODE",
    "RESIMPLI_ADAPTER_PATH",
    "RESIMPLI_ADAPTER_VERIFIED",
    # Opener identity for every draft path (not a secret, but it is process config).
    "SENDER_NAME",
    "COMPANY_NAME",
}


SECRET_KEY = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def write_private(values):
    """Change one of the allow-listed connector settings from the Settings screen."""
    if not set(values).issubset(ALLOWED):
        raise ValueError("This private setting cannot be changed here")
    _write(values)


def write_secret(values):
    """Store a named secret (the secret store's own namespace, never the Settings keys).

    Only the secret store uses this. The allow-list above still governs anything the
    HTTP Settings screen can change.
    """
    if not all(SECRET_KEY.match(str(key)) for key in values):
        raise ValueError("Secret names must be upper snake case")
    _write(values)


def _write(values):
    path = config.private_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with LOCK:
        previous = dict(dotenv_values(path)) if path.exists() else {}
        for key, value in values.items():
            if value is None:
                previous.pop(key, None)
            else:
                if key.endswith("API_KEY") and (
                    len(str(value)) < 16
                    or len(str(value)) > 2000
                    or any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in str(value))
                ):
                    raise ValueError("API key format is invalid; do not include spaces or control characters")
                previous[key] = str(value).lower() if isinstance(value, bool) else str(value)
        descriptor, temporary = tempfile.mkstemp(prefix=".env.secrets.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
                file.write("# PRIVATE BACKEND SETTINGS — never package or commit this file.\n")
                for key, value in sorted(previous.items()):
                    if value is not None:
                        file.write(key + "=" + json.dumps(value, ensure_ascii=True) + "\n")
                file.flush()
                os.fsync(file.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
    config.get_settings.cache_clear()


def save_adapter(text, verified):
    from .resimpli import ResponseAdapter

    if len(text) > 150000:
        raise ValueError("Adapter exceeds the size limit")
    try:
        value = ResponseAdapter.model_validate_json(text)
    except Exception:
        raise ValueError("Invalid adapter JSON; verify the response contract using the integration guide") from None
    if not value.leads.fields.get("external_id") or not value.leads.list_path:
        raise ValueError("A stable external lead ID and list path must be explicitly mapped")
    if not verified:
        raise ValueError(
            "Explicitly confirm that this adapter matches actual authorized account responses, not the fictional fixture"
        )
    if "SYNTHETIC FIXTURE" in value.description.upper():
        raise ValueError("The synthetic fixture adapter is not a verified live response contract")
    # The adapter is the person's own verified file, so it belongs with their data.
    folder = config.DATA_ROOT / "data"
    folder.mkdir(exist_ok=True)
    destination = folder / "private-resimpli-adapter.json"
    descriptor, temporary = tempfile.mkstemp(prefix=".adapter-", dir=folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(value.model_dump_json(indent=2))
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    write_private({"RESIMPLI_ADAPTER_PATH": str(destination), "RESIMPLI_ADAPTER_VERIFIED": True})


def environment_overrides():
    return {
        "groq": any(name in os.environ for name in ("GROQ_API_KEY", "GROQ_ENABLED", "GROQ_MODEL")),
        "resimpli": any(
            name in os.environ for name in ("RESIMPLI_API_KEY", "RESIMPLI_MODE", "RESIMPLI_ADAPTER_VERIFIED")
        ),
    }
