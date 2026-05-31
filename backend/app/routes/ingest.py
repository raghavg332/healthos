from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.ai.parser import parse_health_message
from app.config import settings
from app.db.client import db

router = APIRouter(prefix="/ingest", tags=["ingest"])

# Fields that belong in daily_logs
DAILY_FIELDS = {"weight_kg", "sleep_hrs", "sleep_qual", "energy", "stress", "notes"}

# Fields that belong in nutrition_logs
NUTRITION_FIELDS = {"calories", "protein_g", "carbs_g", "fat_g", "fibre_g"}


class TelegramPayload(BaseModel):
    user_id: int
    text: str
    message_date: Optional[date] = None  # defaults to today if omitted


class EvoltPayload(BaseModel):
    scan_date: date
    weight_kg: Optional[float] = None
    body_fat_pct: Optional[float] = None
    muscle_mass_kg: Optional[float] = None
    visceral_fat: Optional[float] = None
    bmr: Optional[int] = None
    bmi: Optional[float] = None
    notes: Optional[str] = None


@router.post("/telegram")
async def ingest_telegram(payload: TelegramPayload):
    # Gate to single allowed user
    if payload.user_id != settings.telegram_allowed_user_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # NLP parse
    metrics = parse_health_message(payload.text)

    if not metrics:
        return {"status": "ok", "parsed": {}, "message": "Nothing health-related found"}

    log_date = (payload.message_date or date.today()).isoformat()

    daily = {k: v for k, v in metrics.items() if k in DAILY_FIELDS}
    nutrition = {k: v for k, v in metrics.items() if k in NUTRITION_FIELDS}

    # Upsert daily_logs
    if daily:
        result = (
            db()
            .table("daily_logs")
            .upsert({"date": log_date, "raw_input": payload.text, **daily}, on_conflict="date")
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to upsert daily log")

    # Upsert nutrition_logs
    if nutrition:
        result = (
            db()
            .table("nutrition_logs")
            .upsert({"date": log_date, **nutrition}, on_conflict="date")
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=500, detail="Failed to upsert nutrition log")

    return {"status": "ok", "parsed": metrics, "date": log_date}


@router.post("/evolt-photo")
async def ingest_evolt_photo(request: Request):
    from app.ai.scan_parser import parse_scan_image

    image_bytes = await request.body()
    content_type = request.headers.get("content-type", "image/jpeg")
    scan_date = request.headers.get("x-scan-date", date.today().isoformat())

    if not image_bytes:
        raise HTTPException(status_code=400, detail="No image data received")

    extracted = parse_scan_image(image_bytes, mime_type=content_type)

    if not extracted:
        raise HTTPException(status_code=422, detail="Could not extract body comp data from image")

    row = {"scan_date": scan_date, **extracted}
    result = db().table("body_comp_scans").insert(row).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to insert scan")

    return {"status": "ok", "scan_date": scan_date, "extracted": extracted}


@router.post("/evolt")
async def ingest_evolt(payload: EvoltPayload):
    row = payload.model_dump(exclude_none=True)
    row["scan_date"] = payload.scan_date.isoformat()

    result = db().table("body_comp_scans").insert(row).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to insert scan")

    return {"status": "ok", "scan_date": payload.scan_date.isoformat()}
