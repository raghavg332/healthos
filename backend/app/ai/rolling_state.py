"""
Rolling state — the AI's compact long-term memory.
Single row in the rolling_state table, always upserted never appended.
"""

import json
from app.db.client import db


def get_rolling_state() -> dict:
    """Return the current rolling state as a dict."""
    result = db().rpc("get_rolling_state", {}).execute()
    state = result.data
    if isinstance(state, str):
        state = json.loads(state)
    return state or {}


def upsert_rolling_state(new_state: dict) -> None:
    """Replace the rolling state with a new dict."""
    # Use direct table upsert — more reliable than the RPC for edge cases
    existing = db().table("rolling_state").select("id").limit(1).execute()
    if existing.data:
        db().table("rolling_state").update(
            {"state": new_state}
        ).eq("id", existing.data[0]["id"]).execute()
    else:
        db().table("rolling_state").insert({"state": new_state}).execute()


def rolling_state_as_text() -> str:
    """Return rolling state as a formatted string for inclusion in prompts."""
    state = get_rolling_state()
    return json.dumps(state, indent=2)
