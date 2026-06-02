"""
Text-to-SQL /ask agent.

Flow:
  1. LLM turns the question into ONE read-only Postgres SELECT (schema-aware).
  2. Query runs via the run_readonly_query RPC (SELECT-only, 5s timeout).
  3. If the query errors, the error is fed back to the LLM once for a fix.
  4. LLM answers the question in natural language from the rows.
"""

import json
from datetime import date

from app.ai.gemini import generate
from app.ai.rolling_state import rolling_state_as_text
from app.db.client import db

SCHEMA = """Postgres tables (single user — no user_id columns):

daily_logs(date date, weight_kg float, sleep_hrs float, sleep_qual int, energy int, stress int, notes text)
  -- manual Telegram logs; one row per day

nutrition_logs(date date, calories float, protein_g float, carbs_g float, fat_g float, fibre_g float)
  -- one row per day

workouts(date date, title text, duration_mins int, volume_kg float, exercises jsonb)
  -- from Hevy. `exercises` is a jsonb ARRAY of objects:
  --   [{ "title": "Bench Press (Barbell)",
  --      "notes": "...",
  --      "sets": [{ "reps": 12, "weight_kg": 60, "type": "normal" }, ...] }, ...]
  -- To dig into sets, unnest with jsonb_array_elements.

body_comp_scans(scan_date date, weight_kg float, body_fat_pct float, muscle_mass_kg float,
                visceral_fat float, bmr int, bmi float, notes text)
  -- Evolt/InBody scans, sparse (every few months)

ai_insights(insight_type text, period_start date, period_end date, response text, created_at timestamptz)
  -- insight_type in ('daily_nudge','weekly_review','ad_hoc')

job_runs(job_name text, status text, message text, duration_ms int, created_at timestamptz)
"""

SQL_SYSTEM = """You translate a health/fitness question into exactly ONE read-only Postgres SELECT query.

{schema}

Rules:
- Output ONLY the SQL. No explanation, no markdown fences, no trailing semicolon.
- SELECT (or WITH ... SELECT) only. Never INSERT/UPDATE/DELETE/DDL.
- Always include a LIMIT of 200 or fewer.
- Today's date is {today}. Use it for relative ranges ("last week", "this month").
- To analyse specific lifts, unnest exercises, e.g.:
    select w.date, ex->>'title' as exercise,
           (s->>'weight_kg')::float as weight_kg, (s->>'reps')::int as reps
    from workouts w,
         jsonb_array_elements(w.exercises) ex,
         jsonb_array_elements(ex->'sets') s
    where ex->>'title' ilike '%bench%'
    order by w.date desc limit 200
- Prefer returning raw rows the answer can be derived from over pre-aggregating, unless the question is clearly an aggregate."""

ANSWER_SYSTEM = """You are a personal strength & physique coach. Answer the user's question using ONLY the SQL result rows provided.

Focus on gym progress, diet, and weight. Be concise (under 300 words), cite actual numbers from the rows.
If the rows are empty or don't answer the question, say so plainly — do not invent numbers."""


def _clean_sql(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("sql"):
            raw = raw[3:]
        raw = raw.strip()
    return raw.rstrip(";").strip()


def _gen_sql(question: str, today: str, prior_error: str = "", prior_sql: str = "") -> str:
    system = SQL_SYSTEM.format(schema=SCHEMA, today=today)
    user = f"Question: {question}"
    if prior_error:
        user = (
            f"Question: {question}\n\n"
            f"Your previous query failed:\n{prior_sql}\n\n"
            f"Error: {prior_error}\n\n"
            f"Return a corrected query."
        )
    return _clean_sql(generate(system=system, user=user, temperature=0))


def _run_sql(sql: str) -> list:
    return db().rpc("run_readonly_query", {"query": sql}).execute().data or []


def answer_question(question: str) -> dict:
    """Return {answer, sql, rows}. Generates SQL, runs it (one retry on error), answers."""
    today = date.today().isoformat()

    sql = _gen_sql(question, today)
    try:
        rows = _run_sql(sql)
    except Exception as e:
        sql = _gen_sql(question, today, prior_error=str(e), prior_sql=sql)
        rows = _run_sql(sql)

    answer_context = f"""=== ROLLING STATE (goals & context) ===
{rolling_state_as_text()}

=== QUESTION ===
{question}

=== SQL RUN ===
{sql}

=== RESULT ROWS ===
{json.dumps(rows, indent=2, default=str)}

Today: {today}"""

    answer = generate(system=ANSWER_SYSTEM, user=answer_context, temperature=0.4)
    return {"answer": answer, "sql": sql, "rows": rows}
