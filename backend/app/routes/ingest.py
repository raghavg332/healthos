from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.ai.parser import parse_health_message
from app.config import settings
from app.db.client import db

router = APIRouter(prefix="/ingest", tags=["ingest"])


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

    # Upsert into daily_logs (date is the unique key)
    log_date = payload.message_date or date.today()

    row = {
        "date": log_date.isoformat(),
        "raw_input": payload.text,
        **metrics,
    }

    result = (
        db()
        .table("daily_logs")
        .upsert(row, on_conflict="date")
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to upsert daily log")

    return {"status": "ok", "parsed": metrics, "date": log_date.isoformat()}


@router.post("/evolt")
async def ingest_evolt(payload: EvoltPayload):
    row = payload.model_dump(exclude_none=True)
    row["scan_date"] = payload.scan_date.isoformat()

    result = db().table("body_comp_scans").insert(row).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to insert scan")

    return {"status": "ok", "scan_date": payload.scan_date.isoformat()}
