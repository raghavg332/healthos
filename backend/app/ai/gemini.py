"""
Shared Gemini client and generate helper.
All AI calls in the app go through here.
"""

from google import genai
from google.genai import types
from app.config import settings

client = genai.Client(api_key=settings.gemini_api_key)


def generate(system: str, user: str, temperature: float = 0.7) -> str:
    """Single-turn generation. Returns the response text."""
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
        ),
    )
    return response.text.strip()
