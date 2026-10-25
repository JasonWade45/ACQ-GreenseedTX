# syntax=docker/dockerfile:1
# Acquisitions Assistant AI — single-process same-origin server (FastAPI + prebuilt SPA).
# The interface is already built in frontend/dist, so Node is NOT needed in the image.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000 \
    DATABASE_URL=sqlite:////app/data/acquisitions.db

WORKDIR /app

# Dependencies first, so editing source does not invalidate this layer.
COPY backend/requirements-lock.txt backend/requirements-lock.txt
RUN pip install --no-cache-dir -r backend/requirements-lock.txt

COPY . .

# Verify the bundled UI, then drop root privileges.
RUN test -f frontend/dist/index.html \
 && groupadd --system --gid 10001 appuser \
 && useradd --system --uid 10001 --gid appuser --no-create-home appuser \
 && mkdir -p /app/data \
 && chmod +x /app/deploy/docker-entrypoint.sh \
 && chown -R appuser:appuser /app/data /app/backend /app/frontend/dist /app/scripts /app/deploy

USER appuser

EXPOSE 8000

# Honour $PORT so the same image works on Render/Railway/Fly/Cloud Run and locally.
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health', timeout=4).status == 200 else 1)"

# scripts/run.py refuses a non-loopback bind without APP_ACCESS_PASSWORD >= 12 characters.
ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
