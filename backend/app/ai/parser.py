"""
NLP parser — turns a raw Telegram message into structured health metrics
using Groq (llama-3.3-70b-versatile). Returns a dict with only the keys
that were mentioned.
"""

import json
from datetime import date

from app.ai.gemini import generate

SYSTEM_PROMPT = """Extract health metrics from the user message.
Today's date is {today} ({weekday}). Use it to resolve any relative dates.
Return JSON only, no explanation, no markdown fences. Keys (all optional):
  date        — the day the entry refers to, as YYYY-MM-DD. Resolve relative
                references ("yesterday", "last sunday", "2 days ago") and
                absolute ones ("May 30", "2026-05-30") against today's date.
                OMIT this key entirely if no day is mentioned (it defaults to today).
  weight_kg   — body weight in kg (float)
  sleep_hrs   — hours of sleep (float)
  sleep_qual  — sleep quality 1-10 (int)
  energy      — energy level 1-10 (int)
  stress      — stress level 1-10 (int)
  calories    — total calories consumed (float)
  protein_g   — protein in grams (float)
  carbs_g     — carbohydrates in grams (float)
  fat_g       — fat in grams (float)
  fibre_g     — dietary fibre in grams (float)
  notes       — anything else worth recording (string)

Rules:
- Omit keys that are not mentioned or cannot be inferred.
- If the user gives a qualitative description for a 1-10 field (e.g. "sleep was trash"),
  make a reasonable numeric inference and include it.
- Return {{}} if nothing health-related is mentioned.
- Never include keys with null values.
- Return raw JSON only — no markdown, no ```json fences."""


def parse_health_message(text: str) -> dict:
    """
    Parse a raw Telegram message and return a dict of extracted health metrics.
    Returns an empty dict if nothing relevant is found.
    """
    today = date.today()
    system = SYSTEM_PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A"))
    raw = generate(system=system, user=text, temperature=0)

    # Strip markdown fences if present (just in case)
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)
