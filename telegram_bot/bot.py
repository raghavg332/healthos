"""
HealthOS Telegram Bot

Commands:
  (plain message)  → NLP parse → upsert daily_log
  /week            → trigger weekly review on demand
  /ask <question>  → ad hoc query against data
  /evolt           → guided Evolt scan entry flow
  /status          → today's log so far
  /jobs            → show last 5 job_runs (debug)
"""

import asyncio
import logging
import os
import sys

import httpx
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Allow running from repo root or telegram_bot/ dir
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.app.config import settings

logging.basicConfig(
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

API = settings.api_base_url
INTERNAL_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {settings.internal_secret}",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def allowed(update: Update) -> bool:
    return update.effective_user.id == settings.telegram_allowed_user_id


async def send(update: Update, text: str) -> None:
    """Send a message, chunking if over Telegram's 4096-char limit."""
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i : i + 4000])


# ── Handlers ─────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Plain text message → NLP parse → upsert daily_log."""
    if not allowed(update):
        return

    text = update.message.text
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API}/ingest/telegram",
            json={"user_id": update.effective_user.id, "text": text},
        )

    if resp.status_code != 200:
        await send(update, f"⚠️ Error logging entry: {resp.text}")
        return

    data = resp.json()
    parsed = data.get("parsed", {})

    if not parsed:
        await send(update, "🤔 Didn't catch any health metrics — try again?")
        return

    # Friendly confirmation
    lines = ["✅ Logged:"]
    if "weight_kg" in parsed:
        lines.append(f"  • Weight: {parsed['weight_kg']} kg")
    if "sleep_hrs" in parsed:
        lines.append(f"  • Sleep: {parsed['sleep_hrs']} hrs")
    if "sleep_qual" in parsed:
        lines.append(f"  • Sleep quality: {parsed['sleep_qual']}/10")
    if "energy" in parsed:
        lines.append(f"  • Energy: {parsed['energy']}/10")
    if "stress" in parsed:
        lines.append(f"  • Stress: {parsed['stress']}/10")
    if "notes" in parsed:
        lines.append(f"  • Notes: {parsed['notes']}")

    await send(update, "\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — today's log so far."""
    if not allowed(update):
        return

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{API}/query/status")

    if resp.status_code != 200:
        await send(update, f"⚠️ Error fetching status: {resp.text}")
        return

    data = resp.json()
    if data.get("status") == "not implemented":
        await send(update, "🚧 /status not implemented yet")
        return

    await send(update, data.get("message", str(data)))


async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/week — trigger weekly review."""
    if not allowed(update):
        return

    await send(update, "🔄 Running weekly review...")

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{API}/jobs/weekly-review",
            headers=INTERNAL_HEADERS,
            json={},
        )

    if resp.status_code != 200:
        await send(update, f"⚠️ Weekly review failed: {resp.text}")
        return

    data = resp.json()
    if data.get("status") == "not implemented":
        await send(update, "🚧 Weekly review not implemented yet")
    else:
        await send(update, data.get("message", "✅ Weekly review complete"))


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ask <question> — ad hoc query."""
    if not allowed(update):
        return

    question = " ".join(context.args)
    if not question:
        await send(update, "Usage: /ask <your question>")
        return

    await send(update, "🔍 Thinking...")

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(f"{API}/query/ask", params={"q": question})

    if resp.status_code != 200:
        await send(update, f"⚠️ Error: {resp.text}")
        return

    data = resp.json()
    if data.get("status") == "not implemented":
        await send(update, "🚧 /ask not implemented yet")
    else:
        await send(update, data.get("answer", str(data)))


async def cmd_evolt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/evolt — guided Evolt scan entry."""
    if not allowed(update):
        return
    # TODO: multi-step conversation flow
    await send(
        update,
        "🚧 Evolt entry not implemented yet.\n\n"
        "For now, POST directly to /ingest/evolt with your scan data.",
    )


async def cmd_jobs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/jobs — show last 5 job_runs."""
    if not allowed(update):
        return

    from backend.app.db.client import db

    result = (
        db()
        .table("job_runs")
        .select("job_name, status, message, duration_ms, created_at")
        .order("created_at", desc=True)
        .limit(5)
        .execute()
    )

    if not result.data:
        await send(update, "No job runs recorded yet.")
        return

    lines = ["🗂 Last 5 job runs:\n"]
    for row in result.data:
        icon = "✅" if row["status"] == "success" else "❌" if row["status"] == "error" else "⏳"
        duration = f"{row['duration_ms']}ms" if row["duration_ms"] else "—"
        lines.append(
            f"{icon} {row['job_name']} — {row['status']} ({duration})\n"
            f"   {row['created_at'][:19]}"
            + (f"\n   {row['message']}" if row.get("message") else "")
        )

    await send(update, "\n\n".join(lines))


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .build()
    )

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("week", cmd_week))
    app.add_handler(CommandHandler("ask", cmd_ask))
    app.add_handler(CommandHandler("evolt", cmd_evolt))
    app.add_handler(CommandHandler("jobs", cmd_jobs))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting (long polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
