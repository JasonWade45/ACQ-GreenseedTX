"""Hugging Face Gradio-Space entrypoint.

Hugging Face's Docker Spaces now require a paid plan on some accounts, while the
Gradio SDK is still free. A Gradio Space simply runs ``python app.py`` and proxies
port 7860, so this file starts the same FastAPI application with uvicorn instead of
defining a Gradio UI. No Gradio import is required at runtime.

The database is Neon (``DATABASE_URL`` secret); the free Space disk is ephemeral.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
# The FastAPI package lives in backend/app; put backend first so ``app.main`` wins
# over this file's own name.
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

os.environ.setdefault("APP_HOST", "0.0.0.0")
os.environ.setdefault("APP_TIMEZONE", "Africa/Cairo")
PORT = int(os.environ.get("PORT", "7860"))

if not os.environ.get("APP_ACCESS_PASSWORD"):
    raise SystemExit("APP_ACCESS_PASSWORD is required (set it as a Space secret)")

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=PORT,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level="info",
    )
