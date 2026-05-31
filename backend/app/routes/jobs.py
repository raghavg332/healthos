import time
from typing import Optional

from fastapi import APIRouter, Request, HTTPException

from app.config import settings
from app.db.client import db

router = APIRouter(prefix="/jobs", tags=["jobs"])


def verify_internal_secret(request: Request) -> None:
    token = request.headers.get("Authorization", "")
    if token != f"Bearer {settings.internal_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


def log_job(job_name: str, status: str, message: Optional[str] = None, duration_ms: Optional[int] = None) -> None:
    db().table("job_runs").insert({
        "job_name":    job_name,
        "status":      status,
        "message":     message,
        "duration_ms": duration_ms,
    }).execute()


@router.post("/sync-hevy")
async def sync_hevy_route(request: Request):
    verify_internal_secret(request)
    log_job("sync-hevy", "started")
    start = time.monotonic()

    try:
        from app.ingestion.hevy import sync_hevy
        result = sync_hevy()
        duration_ms = int((time.monotonic() - start) * 1000)
        msg = f"Synced {result['synced']} workouts across {result['pages']} pages"
        log_job("sync-hevy", "success", msg, duration_ms)
        return {"status": "success", "message": msg}

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_job("sync-hevy", "error", str(e), duration_ms)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-cronometer")
async def sync_cronometer(request: Request):
    verify_internal_secret(request)
    # TODO: pull Cronometer API → upsert nutrition_logs
    return {"status": "not implemented"}


@router.post("/nutrition-nudge")
async def nutrition_nudge(request: Request):
    verify_internal_secret(request)
    log_job("nutrition-nudge", "started")
    start = time.monotonic()

    try:
        from datetime import date
        from app.db.client import db
        from app.telegram import send_message

        # Check if nutrition already logged today
        today = date.today().isoformat()
        result = db().table("nutrition_logs").select("calories, protein_g").eq("date", today).execute()

        if result.data and result.data[0].get("calories"):
            row = result.data[0]
            msg = f"✅ Nutrition already logged today — {row['calories']} kcal, {row['protein_g']}g protein. Good work!"
        else:
            msg = (
                "🍽 *Evening check-in!*\n\n"
                "How did nutrition go today? Send me a message like:\n\n"
                "_\"2200 cals, 180g protein, 60g fat, 200g carbs\"_\n\n"
                "or just the highlights:\n\n"
                "_\"hit 175g protein today, around 2100 cals\"_"
            )

        send_message(msg)
        duration_ms = int((time.monotonic() - start) * 1000)
        log_job("nutrition-nudge", "success", "Nudge sent", duration_ms)
        return {"status": "success", "message": "Nudge sent"}

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_job("nutrition-nudge", "error", str(e), duration_ms)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/daily-nudge")
async def daily_nudge(request: Request):
    verify_internal_secret(request)
    # TODO: build context → Gemini → send Telegram message
    return {"status": "not implemented"}


@router.post("/weekly-review")
async def weekly_review(request: Request):
    verify_internal_secret(request)
    # TODO: full weekly review flow
    return {"status": "not implemented"}
