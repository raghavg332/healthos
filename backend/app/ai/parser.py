"""
NLP parser — turns a raw Telegram message into structured health metrics
using Gemini. Returns a dict with only the keys that were mentioned.
"""

import json
from google import genai
from google.genai import types
from app.config import settings

client = genai.Client(api_key=settings.gemini_api_key)

SYSTEM_PROMPT = """Extract health metrics from the user message.
Return JSON only, no explanation. Keys (all optional):
  weight_kg   — body weight in kg (float)
  sleep_hrs   — hours of sleep (float)
  sleep_qual  — sleep quality 1-10 (int)
  energy      — energy level 1-10 (int)
  stress      — stress level 1-10 (int)
  notes       — anything else worth recording (string)

Rules:
- Omit keys that are not mentioned or cannot be inferred.
- If the user gives a qualitative description for a 1-10 field (e.g. "sleep was trash"),
  make a reasonable numeric inference and include it.
- Return {} if nothing health-related is mentioned.
- Never include keys with null values."""


def parse_health_message(text: str) -> dict:
    """
    Parse a raw Telegram message and return a dict of extracted health metrics.
    Returns an empty dict if nothing relevant is found.
    """
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0,
        ),
    )

    raw = response.text.strip()

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    return json.loads(raw)
