"""
Hevy API sync — pulls all workouts and upserts into the workouts table.
Paginates through all pages. Safe to re-run (idempotent upserts on hevy_id).
"""

from datetime import datetime, timezone
from typing import Optional

import httpx

from app.config import settings
from app.db.client import db

HEVY_BASE = "https://api.hevyapp.com/v1"
PAGE_SIZE = 10  # Hevy max


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _compute_volume_kg(exercises: list) -> float:
    """Total tonnage: sum of weight_kg * reps across all normal/failure/dropset sets."""
    total = 0.0
    for ex in exercises:
        for s in ex.get("sets", []):
            if s.get("type") in ("normal", "failure", "dropset"):
                w = s.get("weight_kg") or 0.0
                r = s.get("reps") or 0
                total += w * r
    return round(total, 2)


def _workout_to_row(w: dict) -> dict:
    start = _parse_dt(w.get("start_time"))
    end = _parse_dt(w.get("end_time"))

    duration_mins = None
    if start and end:
        duration_mins = int((end - start).total_seconds() / 60)

    date = start.date().isoformat() if start else None

    return {
        "hevy_id":       w["id"],
        "date":          date,
        "title":         w.get("title"),
        "duration_mins": duration_mins,
        "volume_kg":     _compute_volume_kg(w.get("exercises", [])),
        "exercises":     w.get("exercises", []),
    }


def sync_hevy() -> dict:
    """
    Pull all workouts from Hevy API and upsert into Supabase.
    Returns a summary dict: {synced, pages}.
    """
    headers = {"api-key": settings.hevy_api_key}
    page = 1
    total_synced = 0
    total_pages = 1

    with httpx.Client(timeout=30) as client:
        while page <= total_pages:
            resp = client.get(
                f"{HEVY_BASE}/workouts",
                headers=headers,
                params={"page": page, "pageSize": PAGE_SIZE},
            )
            resp.raise_for_status()
            data = resp.json()

            total_pages = data.get("page_count", 1)
            workouts = data.get("workouts", [])

            if not workouts:
                break

            rows = [_workout_to_row(w) for w in workouts]

            db().table("workouts").upsert(rows, on_conflict="hevy_id").execute()
            total_synced += len(rows)
            page += 1

    return {"synced": total_synced, "pages": total_pages}
