from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException

from app.ai.ask_agent import answer_question
from app.db.client import db

router = APIRouter(prefix="/query", tags=["query"])


@router.get("/ask")
async def ask(q: str):
    if not q.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    result = answer_question(q)

    # Store in ai_insights (prompt records the SQL that was run, for audit)
    db().table("ai_insights").insert({
        "insight_type": "ad_hoc",
        "period_start":  date.today().isoformat(),
        "period_end":    date.today().isoformat(),
        "prompt":        f"Q: {q}\n\nSQL: {result['sql']}",
        "response":      result["answer"],
        "model":         "groq",
    }).execute()

    return {"status": "ok", "answer": result["answer"]}


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
