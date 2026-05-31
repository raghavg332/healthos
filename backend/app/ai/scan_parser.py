"""
Evolt body composition scan parser.
Takes raw image bytes, sends to Gemini vision, returns structured scan data.
"""

import json
from google import genai
from google.genai import types
from app.config import settings

client = genai.Client(api_key=settings.gemini_api_key)

SYSTEM_PROMPT = """You are extracting body composition data from a scan printout (e.g. Evolt 360, InBody, DEXA or similar).

Look carefully at all numbers on the image and return a JSON object with these keys (all optional — only include what you can clearly read):
  weight_kg        — total body weight in kg (float)
  body_fat_pct     — body fat percentage (float, e.g. 18.5)
  muscle_mass_kg   — skeletal muscle mass in kg (float)
  visceral_fat     — visceral fat level or rating (float)
  bmr              — basal metabolic rate in kcal (int)
  bmi              — body mass index (float)
  notes            — any other relevant info visible on the scan (string)

Rules:
- Return ONLY valid JSON, no explanation
- Omit keys you cannot clearly read
- Do not guess or estimate — only extract clearly visible numbers
- If units are shown (lbs vs kg), convert to kg
- Return {} if you cannot read any body composition data from the image"""


def parse_scan_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    """
    Extract body composition metrics from a scan image.
    Returns a dict of extracted fields (only keys that were readable).
    """
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            "Extract the body composition data from this scan printout.",
        ],
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
