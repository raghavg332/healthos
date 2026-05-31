"""
Weekly review — the main AI coaching flow.

Flow:
  1. Assemble weekly context
  2. Gemini → review text
  3. Store prompt + response in ai_insights
  4. Second Gemini call → updated rolling_state JSON
  5. Upsert rolling_state
  6. Send review to Telegram
"""

import json
from datetime import date, timedelta

from app.ai.context_builder import build_weekly_context, _get_week_start
from app.ai.gemini import generate
from app.ai.rolling_state import rolling_state_as_text, upsert_rolling_state
from app.db.client import db
from app.telegram import send_message

REVIEW_SYSTEM = """You are a personal health coach for a software engineer in Singapore doing a body recomp (lose fat, gain muscle).

You have access to their full week of data: training, nutrition, sleep, weight, energy and stress.

Write a weekly review that is:
- Honest and direct — don't sugarcoat but don't be harsh
- Specific — reference actual numbers from the data
- Actionable — end with 2-3 clear priorities for next week
- Concise — aim for 400-600 words

Structure:
1. **Week Summary** — one paragraph overview
2. **Training** — volume, consistency, notable sessions
3. **Nutrition** — calories, protein, consistency
4. **Recovery** — sleep, energy, stress trends
5. **Body Composition** — weight trend this week
6. **Next Week Priorities** — 2-3 specific, actionable items"""

ROLLING_STATE_SYSTEM = """You are updating a compact JSON memory document for a personal health AI coach.

Given the weekly review text and the current rolling state, produce an updated rolling state JSON.
Return ONLY valid JSON, no explanation.

The rolling state schema:
{
  "last_updated": "YYYY-MM-DD",
  "goals": {
    "primary": "string",
    "target_date": "YYYY-MM-DD or null",
    "current_trajectory": "on track | behind | ahead"
  },
  "trends": {
    "weight": "string describing recent trend",
    "strength": "string describing recent trend",
    "sleep": "string describing recent trend",
    "nutrition": "string describing recent trend"
  },
  "known_patterns": ["list of observed behavioural patterns"],
  "active_recommendations": [
    {"rec": "string", "since": "YYYY-MM-DD", "status": "in progress | done | stale"}
  ],
  "flags": [
    {"flag": "string", "severity": "low | medium | high"}
  ]
}

Rules:
- Keep known_patterns to max 5 most relevant
- Keep active_recommendations to max 5
- Remove stale flags and recommendations
- Update trends based on this week's data
- Preserve goals unless there is clear evidence to change them"""


def run_weekly_review() -> str:
    """
    Execute the full weekly review flow.
    Returns the review text that was sent to Telegram.
    """
    today = date.today()
    week_start = _get_week_start(today)

    # 1. Assemble context
    context = build_weekly_context()

    # 2. Generate review
    review_text = generate(system=REVIEW_SYSTEM, user=context, temperature=0.7)

    # 3. Store in ai_insights
    db().table("ai_insights").insert({
        "insight_type":  "weekly_review",
        "period_start":  week_start.isoformat(),
        "period_end":    today.isoformat(),
        "prompt":        context,
        "response":      review_text,
        "model":         "gemini",
    }).execute()

    # 4. Update rolling state
    rolling_state_prompt = f"""Current rolling state:
{rolling_state_as_text()}

This week's review:
{review_text}

Today's date: {today.isoformat()}

Produce the updated rolling state JSON."""

    updated_state_raw = generate(
        system=ROLLING_STATE_SYSTEM,
        user=rolling_state_prompt,
        temperature=0.2,
    )

    # Strip markdown fences if present
    raw = updated_state_raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    updated_state = json.loads(raw)

    # 5. Upsert rolling state
    upsert_rolling_state(updated_state)

    # 6. Send to Telegram
    header = f"📊 *Weekly Review — w/c {week_start.strftime('%d %b %Y')}*\n\n"
    send_message(header + review_text)

    return review_text
