from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.services.metrics import dashboard_metrics

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/metrics")
def dashboard(db: Session = Depends(get_db)):
    return dashboard_metrics(db)
