"""
Utility to send Telegram messages to the allowed user.
Used by job routes (nudges, weekly review) to push outbound messages.
"""

import httpx
from app.config import settings

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


def send_message(text: str) -> None:
    """Send a message to the configured Telegram user. Chunks if over 4000 chars."""
    for i in range(0, len(text), 4000):
        chunk = text[i : i + 4000]
        with httpx.Client(timeout=15) as client:
            client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={
                    "chat_id": settings.telegram_allowed_user_id,
                    "text": chunk,
                    "parse_mode": "Markdown",
                },
            ).raise_for_status()
