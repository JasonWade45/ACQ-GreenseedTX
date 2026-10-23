"""FastAPI application entry point.

Run locally (development):
    uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

The server binds to localhost by default. Seller lead data is confidential —
do not expose this service to a network without adding authentication first.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import SessionLocal, init_db

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("acquisitions")


def _run_migrations() -> None:
    """Apply Alembic migrations when available; fall back to create_all."""
    from pathlib import Path

    try:
        from alembic import command
        from alembic.config import Config

        backend_dir = Path(__file__).resolve().parent.parent
        cfg = Config(str(backend_dir / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_dir / "alembic"))
        cfg.set_main_option("sqlalchemy.url", settings.database_url)
        command.upgrade(cfg, "head")
        logger.info("Database migrations applied")
    except Exception as exc:  # noqa: BLE001
        logger.info("Alembic upgrade skipped (%s) — using create_all bootstrap", exc)
        init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()

    from app.models import AppSetting
    from app.scheduler import configure_scheduler

    enabled = bool(settings.sync_enabled)
    session = SessionLocal()
    try:
        row = session.get(AppSetting, "sync_enabled")
        if row is not None:
            enabled = bool(row.value)
    except Exception:  # pragma: no cover
        logger.exception("Could not read sync_enabled setting")
    finally:
        session.close()

    if enabled:
        configure_scheduler(True, settings.sync_interval_minutes)
        logger.info("Periodic REsimpli sync enabled")
    yield

    from app.scheduler import stop_scheduler

    stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        description=(
            "Local acquisitions assistant for US residential seller leads. "
            "REsimpli remains the source of truth. This application never sends "
            "messages, emails or calls to sellers."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ValueError)
    async def value_error_handler(_request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    from app.api.router import api_router

    app.include_router(api_router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "app": settings.app_name,
            "environment": settings.environment,
            "note": "This application never contacts sellers automatically.",
        }

    return app


app = create_app()


def run() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
