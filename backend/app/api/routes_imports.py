"""Import center endpoints: upload, inspect, preview, commit, reports."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.services import import_service, settings_service
from app.services.resimpli_client import ResimpliAuthError, ResimpliError

router = APIRouter(tags=["import center"])


class MappingPayload(BaseModel):
    mapping: dict[str, Optional[str]]


class AiMapPayload(BaseModel):
    file: str
    sheet_name: Optional[str] = None
    mapping: dict[str, Optional[str]] = {}


class TemplatePayload(BaseModel):
    name: str
    mapping: dict[str, Optional[str]]


class CommitPayload(BaseModel):
    record_ids: Optional[list[str]] = None
    skip_duplicates: bool = True
    external: Optional[dict[str, Any]] = None


class ExternalConfigPayload(BaseModel):
    pipelineId: Optional[str] = None
    mainStatusId: Optional[str] = None
    marketId: Optional[str] = None
    marketingCampignId: Optional[str] = None
    propertyType: Optional[str] = None


@router.get("/imports/fields")
def field_catalogue():
    return {
        "fields": [{"key": s["key"], "label": s["label"], "type": s["type"]} for s in import_service.FIELD_SPECS],
        "required_any_of": ["phone", "email", "first_name + address"],
    }


@router.post("/imports/upload")
async def upload_and_inspect(file: UploadFile = File(...), sheet_name: Optional[str] = Form(None)):
    if not file.filename:
        raise ValueError("No file provided")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xlsm"}:
        raise ValueError("Only .csv and .xlsx files are supported")
    path, safe_name = import_service.upload_path(file.filename)
    size = 0
    max_bytes = settings.max_upload_mb * 1024 * 1024
    with path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                path.unlink(missing_ok=True)
                raise ValueError(f"File exceeds the {settings.max_upload_mb} MB limit")
            out.write(chunk)
    inspection = import_service.inspect_file(path, safe_name, sheet_name)
    if inspection.error:
        path.unlink(missing_ok=True)
        raise ValueError(inspection.error)
    # stash the checksum in the filename so preview can find it again
    final = path.with_name(f"{inspection.checksum[:16]}_{safe_name}")
    shutil.move(str(path), str(final))
    data = inspection.to_dict()
    data["stored_path"] = final.name
    data["checksum"] = inspection.checksum
    return data


@router.post("/imports/preview")
def preview(payload: MappingPayload, file: str, sheet_name: Optional[str] = None, db: Session = Depends(get_db)):
    path = Path(settings.upload_dir) / file
    if not path.exists():
        raise ValueError("Uploaded file not found — upload it again")
    result = import_service.preview_import(db, path, path.name.split("_", 1)[-1], {k: v for k, v in payload.mapping.items() if v}, sheet_name)
    return result


@router.post("/imports/ai-map")
def ai_map(payload: AiMapPayload):
    path = Path(settings.upload_dir) / payload.file
    if not path.exists():
        raise ValueError("Uploaded file not found — upload it again")
    return import_service.ai_map_for_file(
        path,
        path.name.split("_", 1)[-1],
        {k: v for k, v in (payload.mapping or {}).items() if v},
        payload.sheet_name,
    )


@router.get("/imports/external-config")
def get_external_config(db: Session = Depends(get_db)):
    return import_service.external_config(db)


@router.post("/imports/external-config")
def set_external_config(payload: ExternalConfigPayload, db: Session = Depends(get_db)):
    settings_service.update_resimpli_lead_ids(db, payload.model_dump())
    return import_service.external_config(db)


@router.get("/imports")
def list_batches(db: Session = Depends(get_db)):
    return {"items": import_service.list_batches(db)}


@router.get("/imports/{batch_id}")
def get_batch(batch_id: str, include_records: bool = True, db: Session = Depends(get_db)):
    return import_service.get_batch(db, batch_id, include_records=include_records)


@router.post("/imports/{batch_id}/commit")
def commit(batch_id: str, payload: CommitPayload, db: Session = Depends(get_db)):
    try:
        return import_service.commit_import(
            db,
            batch_id,
            record_ids=payload.record_ids,
            skip_duplicates=payload.skip_duplicates,
            external=payload.external,
        )
    except (ResimpliAuthError, ResimpliError) as exc:
        raise ValueError(str(exc)) from exc


@router.get("/imports/{batch_id}/rejected.csv")
def rejected_csv(batch_id: str, db: Session = Depends(get_db)):
    body = import_service.rejected_records_csv(db, batch_id)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="rejected_{batch_id[:8]}.csv"'},
    )


@router.get("/imports/{batch_id}/resimpli-template.csv")
def resimpli_csv(batch_id: str, db: Session = Depends(get_db)):
    body = import_service.resimpli_template_csv(db, batch_id)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="resimpli_import_{batch_id[:8]}.csv"'},
    )


@router.get("/imports/templates/list")
def templates(db: Session = Depends(get_db)):
    return {"items": import_service.list_templates(db)}


@router.post("/imports/templates")
def save_template(payload: TemplatePayload, db: Session = Depends(get_db)):
    return import_service.save_template(db, payload.name, {k: v for k, v in payload.mapping.items() if v})


@router.delete("/imports/templates/{template_id}")
def delete_template(template_id: str, db: Session = Depends(get_db)):
    import_service.delete_template(db, template_id)
    return {"deleted": True}


@router.get("/imports/{batch_id}/leads")
def batch_leads(batch_id: str, db: Session = Depends(get_db)):
    return {"items": import_service.leads_created_by_batch(db, batch_id)}
