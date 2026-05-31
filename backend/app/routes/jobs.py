from fastapi import APIRouter, Request, HTTPException
from app.config import settings

router = APIRouter(prefix="/jobs", tags=["jobs"])


def verify_internal_secret(request: Request) -> None:
    token = request.headers.get("Authorization", "")
    if token != f"Bearer {settings.internal_secret}":
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/sync-hevy")
async def sync_hevy(request: Request):
    verify_internal_secret(request)
    # TODO: pull Hevy API → upsert workouts
    return {"status": "not implemented"}


@router.post("/sync-cronometer")
async def sync_cronometer(request: Request):
    verify_internal_secret(request)
    # TODO: pull Cronometer API → upsert nutrition_logs
    return {"status": "not implemented"}


@router.post("/daily-nudge")
async def daily_nudge(request: Request):
    verify_internal_secret(request)
    # TODO: build context → Claude → send Telegram message
    return {"status": "not implemented"}


@router.post("/weekly-review")
async def weekly_review(request: Request):
    verify_internal_secret(request)
    # TODO: full weekly review flow
    return {"status": "not implemented"}
