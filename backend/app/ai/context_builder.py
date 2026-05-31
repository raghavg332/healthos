"""
Context builder — assembles token-budgeted prompt data for each query type.

Query types:
  daily_nudge   — rolling_state + yesterday + this week so far
  weekly_review — rolling_state + this week raw + summaries + body comp + insights
  ad_hoc        — rolling_state + vector search results (TODO: embeddings)
"""

import json
from datetime import date, timedelta

from app.db.client import db
from app.ai.rolling_state import rolling_state_as_text


def _get_week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def build_daily_context() -> str:
    """
    Context for the morning daily nudge.
    Returns a formatted string ready to include in a prompt.
    """
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_start = _get_week_start(today)

    # Yesterday's log
    yday_log = (
        db().table("daily_logs")
        .select("*")
        .eq("date", yesterday.isoformat())
        .execute()
    ).data

    yday_nutrition = (
        db().table("nutrition_logs")
        .select("*")
        .eq("date", yesterday.isoformat())
        .execute()
    ).data

    # This week's logs so far (excluding today)
    week_logs = (
        db().table("daily_logs")
        .select("date, weight_kg, sleep_hrs, sleep_qual, energy, stress")
        .gte("date", week_start.isoformat())
        .lt("date", today.isoformat())
        .order("date")
        .execute()
    ).data

    week_nutrition = (
        db().table("nutrition_logs")
        .select("date, calories, protein_g, carbs_g, fat_g")
        .gte("date", week_start.isoformat())
        .lt("date", today.isoformat())
        .order("date")
        .execute()
    ).data

    # This week's workouts
    week_workouts = (
        db().table("workouts")
        .select("date, title, duration_mins, volume_kg")
        .gte("date", week_start.isoformat())
        .lt("date", today.isoformat())
        .order("date")
        .execute()
    ).data

    return f"""
=== ROLLING STATE (AI Memory) ===
{rolling_state_as_text()}

=== YESTERDAY ({yesterday.isoformat()}) ===
Daily log: {json.dumps(yday_log[0] if yday_log else None, indent=2)}
Nutrition: {json.dumps(yday_nutrition[0] if yday_nutrition else None, indent=2)}

=== THIS WEEK SO FAR (since {week_start.isoformat()}) ===
Daily logs:
{json.dumps(week_logs, indent=2)}

Nutrition logs:
{json.dumps(week_nutrition, indent=2)}

Workouts:
{json.dumps(week_workouts, indent=2)}

Today's date: {today.isoformat()}
""".strip()


def build_weekly_context() -> str:
    """
    Context for the weekly review.
    Returns a formatted string ready to include in a prompt.
    """
    today = date.today()
    week_start = _get_week_start(today)

    # This week's raw data
    week_data = db().rpc("get_week_data", {"p_week_start": week_start.isoformat()}).execute().data

    # Last 4 weekly summaries
    weekly_summaries = (
        db().table("weekly_summaries")
        .select("*")
        .lt("week", week_start.isoformat())
        .order("week", desc=True)
        .limit(4)
        .execute()
    ).data

    # Last 6 monthly summaries
    monthly_summaries = (
        db().table("monthly_summaries")
        .select("*")
        .order("month", desc=True)
        .limit(6)
        .execute()
    ).data

    # All body comp scans
    body_comp = (
        db().table("body_comp_scans")
        .select("*")
        .order("scan_date", desc=True)
        .execute()
    ).data

    # Last 2 AI insights
    past_insights = (
        db().table("ai_insights")
        .select("insight_type, period_start, period_end, response")
        .eq("insight_type", "weekly_review")
        .order("created_at", desc=True)
        .limit(2)
        .execute()
    ).data

    return f"""
=== ROLLING STATE (AI Memory) ===
{rolling_state_as_text()}

=== THIS WEEK RAW DATA ({week_start.isoformat()}) ===
{json.dumps(week_data, indent=2)}

=== LAST 4 WEEKLY SUMMARIES ===
{json.dumps(weekly_summaries, indent=2)}

=== LAST 6 MONTHLY SUMMARIES ===
{json.dumps(monthly_summaries, indent=2)}

=== BODY COMPOSITION SCANS ===
{json.dumps(body_comp, indent=2)}

=== LAST 2 WEEKLY REVIEWS ===
{json.dumps(past_insights, indent=2)}

Week being reviewed: {week_start.isoformat()} to {today.isoformat()}
""".strip()
