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


def _has_logged_today() -> bool:
    """Return True if the user has logged anything in daily_logs today."""
    from datetime import date
    result = db().table("daily_logs").select("id").eq("date", date.today().isoformat()).execute()
    return bool(result.data)


def _has_logged_yesterday_nutrition() -> bool:
    """Return True if nutrition was logged for yesterday."""
    from datetime import date, timedelta
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    result = db().table("nutrition_logs").select("id").eq("date", yesterday).execute()
    return bool(result.data)


async def _run_daily_nudge(is_retry: bool = False) -> str:
    """Build context and send the daily nudge. Returns the nudge text."""
    from app.ai.context_builder import build_daily_context
    from app.ai.gemini import generate
    from app.telegram import send_message
    from datetime import date

    context = build_daily_context()

    system = """You are a personal strength & physique coach for a 22-year-old software engineer in Singapore on a 3-month lean recomp (get toned).

FOCUS, in order: GYM PROGRESS, DIET, WEIGHT. Sleep/energy/stress are secondary — mention only if clearly relevant.

Send a brief, motivating morning check-in based on their data. Be specific — reference actual numbers (lifts, protein, weight).
Keep it under 150 words. Structure:
1. One line on yesterday — did they train / hit protein / how's weight tracking vs target
2. The ONE thing to nail today (a lift to progress, a protein target, a training day) based on the data
3. One short line to close

If a prior recommendation is shown in the context, acknowledge whether they followed through on it.
Be direct and human — not corporate wellness speak."""

    nudge_text = generate(system=system, user=context, temperature=0.8)

    db().table("ai_insights").insert({
        "insight_type": "daily_nudge",
        "period_start": date.today().isoformat(),
        "period_end":   date.today().isoformat(),
        "prompt":       context,
        "response":     nudge_text,
        "model":        "groq",
    }).execute()

    prefix = "🌤 *Mid-morning check-in!*\n\n" if is_retry else "☀️ *Good morning!*\n\n"
    send_message(prefix + nudge_text)
    return nudge_text


@router.post("/daily-nudge")
async def daily_nudge(request: Request):
    """
    8am SGT — check if today's vitals and yesterday's nutrition are logged.
    If yes: generate and send the nudge.
    If no: remind the user to log, and let the 12pm retry handle it.
    """
    verify_internal_secret(request)
    log_job("daily-nudge", "started")
    start = time.monotonic()

    try:
        from app.telegram import send_message

        has_today = _has_logged_today()
        has_yesterday_nutrition = _has_logged_yesterday_nutrition()

        missing = []
        if not has_today:
            missing.append("today's sleep / energy / stress")
        if not has_yesterday_nutrition:
            missing.append("yesterday's nutrition")

        if missing:
            send_message(
                "☀️ *Good morning!*\n\n"
                f"Quick reminder — I'm still missing: {', '.join(missing)}.\n\n"
                "Log it and I'll send your proper morning summary at noon. 💪"
            )
            duration_ms = int((time.monotonic() - start) * 1000)
            log_job("daily-nudge", "success", f"Reminder sent — missing: {', '.join(missing)}", duration_ms)
            return {"status": "success", "message": "Reminder sent, retry at noon"}

        nudge_text = await _run_daily_nudge(is_retry=False)
        duration_ms = int((time.monotonic() - start) * 1000)
        log_job("daily-nudge", "success", "Nudge sent", duration_ms)
        return {"status": "success", "message": "Daily nudge sent"}

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_job("daily-nudge", "error", str(e), duration_ms)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/daily-nudge-retry")
async def daily_nudge_retry(request: Request):
    """
    12pm SGT — send the nudge regardless, using whatever data exists by now.
    Only fires if the 8am nudge sent a reminder instead of the full nudge.
    """
    verify_internal_secret(request)
    log_job("daily-nudge-retry", "started")
    start = time.monotonic()

    try:
        # If the 8am nudge already sent (no reminder), skip the retry
        from datetime import date
        today = date.today().isoformat()
        recent = (
            db().table("ai_insights")
            .select("id")
            .eq("insight_type", "daily_nudge")
            .eq("period_start", today)
            .execute()
        )
        if recent.data:
            duration_ms = int((time.monotonic() - start) * 1000)
            log_job("daily-nudge-retry", "success", "Skipped — 8am nudge already sent", duration_ms)
            return {"status": "success", "message": "Skipped — already sent this morning"}

        nudge_text = await _run_daily_nudge(is_retry=True)
        duration_ms = int((time.monotonic() - start) * 1000)
        log_job("daily-nudge-retry", "success", "Retry nudge sent", duration_ms)
        return {"status": "success", "message": "Retry nudge sent"}

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_job("daily-nudge-retry", "error", str(e), duration_ms)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/weekly-review")
async def weekly_review_route(request: Request):
    verify_internal_secret(request)
    log_job("weekly-review", "started")
    start = time.monotonic()

    try:
        from app.ai.weekly_review import run_weekly_review

        review_text = run_weekly_review()

        duration_ms = int((time.monotonic() - start) * 1000)
        msg = f"Review complete ({len(review_text)} chars)"
        log_job("weekly-review", "success", msg, duration_ms)
        return {"status": "success", "message": msg}

    except Exception as e:
        duration_ms = int((time.monotonic() - start) * 1000)
        log_job("weekly-review", "error", str(e), duration_ms)
        raise HTTPException(status_code=500, detail=str(e))
