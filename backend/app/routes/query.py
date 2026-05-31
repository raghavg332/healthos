from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from app.ai.gemini import generate
from app.ai.rolling_state import rolling_state_as_text
from app.db.client import db

router = APIRouter(prefix="/query", tags=["query"])

ASK_SYSTEM = """You are a personal health coach AI with access to a user's health data.

Answer their question directly and specifically, referencing actual numbers from the data provided.
Be concise (under 300 words). If the data doesn't contain enough information to answer, say so clearly.
Do not make up numbers or trends that aren't in the data."""


def _build_ask_context(question: str) -> str:
    today = date.today()
    four_weeks_ago = today - timedelta(weeks=4)

    # Recent daily logs (last 4 weeks)
    daily_logs = (
        db().table("daily_logs")
        .select("date, weight_kg, sleep_hrs, sleep_qual, energy, stress, notes")
        .gte("date", four_weeks_ago.isoformat())
        .order("date", desc=True)
        .execute()
    ).data

    # Recent nutrition (last 4 weeks)
    nutrition = (
        db().table("nutrition_logs")
        .select("date, calories, protein_g, carbs_g, fat_g")
        .gte("date", four_weeks_ago.isoformat())
        .order("date", desc=True)
        .execute()
    ).data

    # Recent workouts (last 4 weeks)
    workouts = (
        db().table("workouts")
        .select("date, title, duration_mins, volume_kg")
        .gte("date", four_weeks_ago.isoformat())
        .order("date", desc=True)
        .execute()
    ).data

    # Body comp scans (all)
    scans = (
        db().table("body_comp_scans")
        .select("scan_date, weight_kg, body_fat_pct, muscle_mass_kg, bmr, notes")
        .order("scan_date", desc=True)
        .execute()
    ).data

    import json
    return f"""=== ROLLING STATE (AI Memory) ===
{rolling_state_as_text()}

=== LAST 4 WEEKS: DAILY LOGS ===
{json.dumps(daily_logs, indent=2)}

=== LAST 4 WEEKS: NUTRITION ===
{json.dumps(nutrition, indent=2)}

=== LAST 4 WEEKS: WORKOUTS ===
{json.dumps(workouts, indent=2)}

=== BODY COMPOSITION SCANS ===
{json.dumps(scans, indent=2)}

Today: {today.isoformat()}

User question: {question}"""


@router.get("/ask")
async def ask(q: str):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    context = _build_ask_context(q)
    answer = generate(system=ASK_SYSTEM, user=context, temperature=0.5)

    # Store in ai_insights
    db().table("ai_insights").insert({
        "insight_type": "ad_hoc",
        "period_start":  date.today().isoformat(),
        "period_end":    date.today().isoformat(),
        "prompt":        context,
        "response":      answer,
        "model":         "gemini",
    }).execute()

    return {"status": "ok", "answer": answer}


@router.get("/status")
async def get_status():
    today = date.today()

    daily = (
        db().table("daily_logs")
        .select("weight_kg, sleep_hrs, sleep_qual, energy, stress, notes")
        .eq("date", today.isoformat())
        .execute()
    ).data

    nutrition = (
        db().table("nutrition_logs")
        .select("calories, protein_g, carbs_g, fat_g")
        .eq("date", today.isoformat())
        .execute()
    ).data

    workouts = (
        db().table("workouts")
        .select("title, duration_mins, volume_kg")
        .eq("date", today.isoformat())
        .execute()
    ).data

    lines = [f"📋 *Today ({today.isoformat()})*\n"]

    if daily:
        d = daily[0]
        lines.append("*Daily log:*")
        if d.get("weight_kg"):   lines.append(f"  • Weight: {d['weight_kg']} kg")
        if d.get("sleep_hrs"):   lines.append(f"  • Sleep: {d['sleep_hrs']} hrs")
        if d.get("sleep_qual"):  lines.append(f"  • Sleep quality: {d['sleep_qual']}/10")
        if d.get("energy"):      lines.append(f"  • Energy: {d['energy']}/10")
        if d.get("stress"):      lines.append(f"  • Stress: {d['stress']}/10")
        if d.get("notes"):       lines.append(f"  • Notes: {d['notes']}")
    else:
        lines.append("_No daily log yet today_")

    lines.append("")

    if nutrition:
        n = nutrition[0]
        lines.append("*Nutrition:*")
        if n.get("calories"):   lines.append(f"  • Calories: {n['calories']} kcal")
        if n.get("protein_g"):  lines.append(f"  • Protein: {n['protein_g']}g")
        if n.get("carbs_g"):    lines.append(f"  • Carbs: {n['carbs_g']}g")
        if n.get("fat_g"):      lines.append(f"  • Fat: {n['fat_g']}g")
    else:
        lines.append("_No nutrition logged yet today_")

    lines.append("")

    if workouts:
        lines.append("*Workouts:*")
        for w in workouts:
            lines.append(f"  • {w['title']} — {w['duration_mins']} mins, {w['volume_kg']} kg volume")
    else:
        lines.append("_No workout logged today_")

    return {"status": "ok", "message": "\n".join(lines)}
