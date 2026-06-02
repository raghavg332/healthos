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

REVIEW_SYSTEM = """You are a personal strength & physique coach for a 22-year-old software engineer in Singapore on a 3-month lean recomp (get toned: drop body fat to ~14%, regain lost muscle).

THE THREE THINGS THAT MATTER MOST, in order: GYM PROGRESS, DIET, WEIGHT.
Sleep/energy/stress are secondary — only mention them if they're clearly affecting training or weight.

You have the full week of data including per-exercise set/rep/weight detail. USE IT.

Write a weekly review that is:
- Honest and direct — don't sugarcoat, don't be harsh
- Specific — cite actual lifts (e.g. "bench 65kg×9, up from last week") and actual macros
- Actionable — end with 2-3 clear priorities for next week
- Concise — aim for 400-600 words

Structure:
1. **Where You Stand** — one paragraph vs the 3-month target (use rolling_state goals/targets)
2. **Gym Progress** — progressive overload per key lift, volume, consistency, leg-day adherence. This is the longest section.
3. **Diet** — calories vs ~2200 target, protein vs 155-165g target, consistency
4. **Weight** — trend this week and vs target trajectory
5. **Next Week Priorities** — 2-3 specific, actionable items focused on gym + diet"""

ROLLING_STATE_SYSTEM = """You are updating a compact JSON memory document for a personal health AI coach.

Given the weekly review text and the current rolling state, produce an updated rolling state JSON.
Return ONLY valid JSON, no explanation.

The rolling state schema (preserve ALL existing keys, including profile, goals.targets, goals.how):
{
  "last_updated": "YYYY-MM-DD",
  "profile": { ... },                      // DO NOT MODIFY — copy through unchanged
  "goals": {
    "primary": "string",
    "target_date": "YYYY-MM-DD or null",
    "targets": { ... },                    // numeric 3-month targets — copy through unchanged
    "how": { ... },                        // the plan — copy through unchanged
    "current_trajectory": "on track | behind | ahead | just started"
  },
  "trends": {
    "weight": "string",
    "body_comp": "string",
    "strength": "string describing per-lift progression",
    "nutrition": "string"
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
- NEVER drop or alter `profile`, `goals.targets`, or `goals.how` — copy them through verbatim
- Only `goals.current_trajectory` may change within goals
- Update trends (especially strength — cite specific lifts) based on this week's data
- Keep known_patterns to max 5, active_recommendations to max 5
- Remove stale flags and recommendations
- Focus recommendations on gym progress, diet, and weight"""


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
        "model":         "groq",
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
