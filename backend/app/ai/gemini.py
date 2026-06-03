"""
Text generation via Groq (llama-3.3-70b-versatile).
All text AI calls go through generate() here.
Gemini is used ONLY for vision — see scan_parser.py.
"""

from typing import Optional
from groq import Groq
from app.config import settings
from app.retry import with_retry

_client: Optional[Groq] = None


def _groq() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=settings.groq_api_key)
    return _client


@with_retry()
def generate(system: str, user: str, temperature: float = 0.7) -> str:
    """Single-turn text generation via Groq. Returns the response text."""
    response = _groq().chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    return response.choices[0].message.content.strip()
