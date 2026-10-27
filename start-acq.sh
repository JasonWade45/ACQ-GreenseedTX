#!/usr/bin/env bash
# Start Acquisitions Assistant on this computer and reach it from any device at home.
# Linux / macOS. The first run creates .venv, installs the locked dependencies and
# generates a private password in .env.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f frontend/dist/index.html ]; then
    echo "The bundled interface is missing. Run this from the complete release folder." >&2
    exit 1
fi

if [ ! -x .venv/bin/python ]; then
    echo "First run: creating the private Python environment..."
    python3 -m venv .venv
fi

if ! .venv/bin/python -c "import fastapi, uvicorn, segno" >/dev/null 2>&1; then
    echo "First run: installing the locked dependencies (no AI model is downloaded)..."
    .venv/bin/python -m pip install --disable-pip-version-check -r backend/requirements-lock.txt
fi

if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    echo "If other devices cannot connect: sudo ufw allow ${PORT:-8010}/tcp"
fi

exec .venv/bin/python scripts/acq_desktop.py --port "${PORT:-8010}" "$@"
