#!/bin/sh
# Container entrypoint: honour the port the platform gives us.
#
# Render, Railway, Fly, Cloud Run and most PaaS providers inject $PORT and expect the
# process to listen on it. Locally (docker compose) no $PORT is set, so it falls back to 8000.
set -eu

PORT="${PORT:-8000}"
HOST="0.0.0.0"

# The app refuses a non-loopback bind without a strong password. Fail loudly at boot instead
# of accepting connections and then rejecting every /api request with 403.
if [ -z "${APP_ACCESS_PASSWORD:-}" ]; then
    echo "FATAL: APP_ACCESS_PASSWORD is empty." >&2
    echo "       Binding $HOST requires a password of at least 12 characters." >&2
    echo "       Set APP_ACCESS_PASSWORD in the platform dashboard or .env, then restart." >&2
    exit 1
fi

if [ "${#APP_ACCESS_PASSWORD}" -lt 12 ]; then
    echo "FATAL: APP_ACCESS_PASSWORD must be at least 12 characters (got ${#APP_ACCESS_PASSWORD})." >&2
    exit 1
fi

# The SQLite database and its WAL files must live on persistent storage.
DATA_DIR="${DATA_DIR:-/app/data}"
mkdir -p "$DATA_DIR"
if [ ! -w "$DATA_DIR" ]; then
    echo "FATAL: $DATA_DIR is not writable. Mount a persistent volume there." >&2
    exit 1
fi
export DATABASE_URL="${DATABASE_URL:-sqlite:///$DATA_DIR/acquisitions.db}"

echo "Starting Acquisitions Assistant on ${HOST}:${PORT}"
echo "Database: ${DATABASE_URL}"
echo "No seller communication, CRM write or automatic cloud request is enabled."

exec python scripts/run.py --host "$HOST" --port "$PORT"
