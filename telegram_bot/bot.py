"""
HealthOS Telegram Bot

Commands:
  (plain message)  → NLP parse → upsert daily_log
  (photo)          → Gemini vision → extract body comp → upsert body_comp_scans
  /week            → trigger weekly review on demand
  /ask <question>  → ad hoc query against data
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
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, REPO_ROOT)

# Locally: chdir to backend/ so pydantic-settings finds .env
# On Railway: env vars are injected directly, no .env needed
_env_file = os.path.join(REPO_ROOT, "backend", ".env")
if os.path.exists(_env_file):
    os.chdir(os.path.join(REPO_ROOT, "backend"))

from backend.app.config import settings
from backend.app.retry import with_retry_async

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

@with_retry_async()
async def api_request(method: str, url: str, *, timeout: float = 30, **kwargs) -> httpx.Response:
    """HTTP call to the backend API, retrying transient transport errors
    (timeouts, connection drops, Railway cold starts). Status codes are
    returned untouched for the caller to handle."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(method, url, **kwargs)


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
    resp = await api_request(
        "POST",
        f"{API}/ingest/telegram",
        json={"user_id": update.effective_user.id, "text": text},
        timeout=30,
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
    if "calories" in parsed:
        lines.append(f"  • Calories: {parsed['calories']} kcal")
    if "protein_g" in parsed:
        lines.append(f"  • Protein: {parsed['protein_g']}g")
    if "carbs_g" in parsed:
        lines.append(f"  • Carbs: {parsed['carbs_g']}g")
    if "fat_g" in parsed:
        lines.append(f"  • Fat: {parsed['fat_g']}g")
    if "notes" in parsed:
        lines.append(f"  • Notes: {parsed['notes']}")

    await send(update, "\n".join(lines))


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/status — today's log so far."""
    if not allowed(update):
        return

    resp = await api_request("GET", f"{API}/query/status", timeout=15)

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

    resp = await api_request(
        "POST",
        f"{API}/jobs/weekly-review",
        headers=INTERNAL_HEADERS,
        json={},
        timeout=120,
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

    resp = await api_request("GET", f"{API}/query/ask", params={"q": question}, timeout=60)

    if resp.status_code != 200:
        await send(update, f"⚠️ Error: {resp.text}")
        return

    data = resp.json()
    if data.get("status") == "not implemented":
        await send(update, "🚧 /ask not implemented yet")
    else:
        await send(update, data.get("answer", str(data)))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Photo message → Gemini vision → extract body comp → upsert body_comp_scans."""
    if not allowed(update):
        return

    await send(update, "📷 Reading your scan...")

    # Download highest-res version of the photo
    photo = update.message.photo[-1]
    tg_file = await context.bot.get_file(photo.file_id)
    image_bytes = bytes(await tg_file.download_as_bytearray())

    # Use caption date if provided, else today
    import re
    from datetime import date
    scan_date = date.today().isoformat()
    if update.message.caption:
        match = re.search(r"\d{4}-\d{2}-\d{2}", update.message.caption)
        if match:
            scan_date = match.group()

    # POST image bytes to API
    resp = await api_request(
        "POST",
        f"{API}/ingest/evolt-photo",
        content=image_bytes,
        headers={
            "content-type": "image/jpeg",
            "x-scan-date": scan_date,
        },
        timeout=60,
    )

    if resp.status_code == 422:
        await send(update, "🤔 Couldn't read body comp data from that image — try a clearer photo.")
        return
    if resp.status_code != 200:
        await send(update, f"⚠️ Error processing scan: {resp.text}")
        return

    extracted = resp.json().get("extracted", {})

    # Confirmation
    lines = [f"✅ Body scan logged for {scan_date}:"]
    if "weight_kg" in extracted:
        lines.append(f"  • Weight: {extracted['weight_kg']} kg")
    if "body_fat_pct" in extracted:
        lines.append(f"  • Body fat: {extracted['body_fat_pct']}%")
    if "muscle_mass_kg" in extracted:
        lines.append(f"  • Muscle mass: {extracted['muscle_mass_kg']} kg")
    if "visceral_fat" in extracted:
        lines.append(f"  • Visceral fat: {extracted['visceral_fat']}")
    if "bmr" in extracted:
        lines.append(f"  • BMR: {extracted['bmr']} kcal")
    if "bmi" in extracted:
        lines.append(f"  • BMI: {extracted['bmi']}")
    if "notes" in extracted:
        lines.append(f"  • Notes: {extracted['notes']}")

    await send(update, "\n".join(lines))


async def cmd_sync(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sync — manually trigger Hevy sync."""
    if not allowed(update):
        return

    await send(update, "🔄 Syncing Hevy...")

    resp = await api_request(
        "POST",
        f"{API}/jobs/sync-hevy",
        headers=INTERNAL_HEADERS,
        json={},
        timeout=60,
    )

    if resp.status_code != 200:
        await send(update, f"⚠️ Sync failed: {resp.text}")
        return

    data = resp.json()
    await send(update, f"✅ {data.get('message', 'Sync complete')}")


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
    app.add_handler(CommandHandler("sync", cmd_sync))
    app.add_handler(CommandHandler("jobs", cmd_jobs))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot starting (long polling)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
