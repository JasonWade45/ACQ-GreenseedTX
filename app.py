"""Hugging Face Gradio-Space entrypoint.

Hugging Face's free Gradio hardware is ZeroGPU, and Docker Spaces now require a paid
plan. The web application is FastAPI, so this file starts it with uvicorn on the port
Hugging Face proxies, and starts a tiny Gradio app on a private port only so the
ZeroGPU startup scan finds a ``@spaces.GPU`` event handler. The Gradio page is never
used by a visitor.

The database is Neon (``DATABASE_URL`` secret); the free Space disk is ephemeral.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT)

os.environ.setdefault("APP_HOST", "0.0.0.0")
os.environ.setdefault("APP_TIMEZONE", "Africa/Cairo")
PORT = int(os.environ.get("PORT", "7860"))

if not os.environ.get("APP_ACCESS_PASSWORD"):
    raise SystemExit("APP_ACCESS_PASSWORD is required (set it as a Space secret)")

# ZeroGPU refuses to start unless a Gradio event handler carries @spaces.GPU. Start a
# minimal Gradio app on a private port; it is never linked from the product UI.
try:
    import gradio as gr
    import spaces

    @spaces.GPU
    def _zerogpu_marker(text: str = "") -> str:
        return "acquisitions-assistant"

    _demo = gr.Interface(fn=_zerogpu_marker, inputs=gr.Textbox(), outputs=gr.Textbox())
    _demo.launch(
        server_name="127.0.0.1",
        server_port=7861,
        prevent_thread_lock=True,
        quiet=True,
        show_api=False,
    )
except Exception as exc:  # local runs do not have gradio/spaces
    print(f"Gradio ZeroGPU marker not started: {exc}")

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
