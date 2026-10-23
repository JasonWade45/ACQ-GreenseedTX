from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    routes_ai,
    routes_dashboard,
    routes_imports,
    routes_leads,
    routes_reports,
    routes_settings,
    routes_sync,
    routes_work,
)

api_router = APIRouter()
api_router.include_router(routes_dashboard.router)
api_router.include_router(routes_leads.router)
api_router.include_router(routes_work.router)
api_router.include_router(routes_imports.router)
api_router.include_router(routes_sync.router)
api_router.include_router(routes_ai.router)
api_router.include_router(routes_reports.router)
api_router.include_router(routes_settings.router)
