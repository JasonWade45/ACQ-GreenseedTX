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
 && chown -R appuser:appuser /app/data /app/backend /app/frontend/dist /app/scripts /app/deploy

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# scripts/run.py refuses a non-loopback bind without APP_ACCESS_PASSWORD >= 12 characters.
CMD ["python", "scripts/run.py", "--host", "0.0.0.0", "--port", "8000"]
