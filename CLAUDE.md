# HealthOS — Claude Code Context

## What We're Building

A personal health operating system for a single user (software engineer, based in Singapore).
Tracks gym, diet, sleep, body composition and weight — with an LLM coaching layer on top
that synthesises all data into actionable guidance.

---

## Core Design Goals

- **Zero friction input** — Telegram bot as the primary mobile interface, natural language logging
- **Automated data ingestion** — Hevy (gym) and Cronometer (nutrition) pulled automatically via API
- **LLM never sees raw data** — all data is pre-aggregated before hitting Claude API
- **Rolling state as memory** — a single compact JSON document (~800 tokens) is the AI's
  long-term memory, updated every weekly review
- **Single user** — no multi-tenancy, no auth complexity, service role only

---

## Tech Stack

| Layer | Technology |
|---|---|
| Database | Supabase (Postgres + pgvector + pg_cron + pg_net) |
| Backend | Python FastAPI (async) |
| AI | Google Gemini API (gemini-2.0-flash) |
| Bot | python-telegram-bot |
| Frontend | Next.js + shadcn/ui + Recharts (later phase) |
| Hosting | Railway (backend + bot as separate services) |
| Frontend hosting | Vercel |
| Migrations | Supabase CLI + GitHub Actions |

---

## Repository Structure

```
healthos/
├── .github/
│   └── workflows/
│       └── migrate.yml          # auto-applies supabase migrations on push to main
├── supabase/
│   ├── config.toml
│   └── migrations/
│       ├── 20240101000000_initial_schema.sql
│       └── 20240115000000_add_job_runs.sql
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py            # pydantic-settings, loads .env
│   │   ├── db/
│   │   │   └── client.py        # supabase client singleton
│   │   ├── ingestion/
│   │   │   ├── hevy.py          # Hevy API sync
│   │   │   ├── cronometer.py    # Cronometer API sync
│   │   │   └── manual.py        # manual entry helpers
│   │   ├── ai/
│   │   │   ├── context_builder.py   # assembles token-budgeted prompt context
│   │   │   ├── parser.py            # NLP parsing of Telegram messages
│   │   │   ├── weekly_review.py     # weekly review agent
│   │   │   └── rolling_state.py     # rolling state update logic
│   │   ├── jobs/
│   │   │   └── scheduler.py     # job endpoint implementations
│   │   └── routes/
│   │       ├── ingest.py        # POST /ingest/*
│   │       ├── jobs.py          # POST /jobs/* (called by pg_cron)
│   │       └── query.py         # GET /query/* (ad hoc queries)
│   ├── pyproject.toml
│   └── .env                     # never committed
├── telegram_bot/
│   └── bot.py
└── frontend/                    # Next.js — later phase
```

---

## Environment Variables (.env)

```env
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...          # service role key, bypasses RLS
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_ALLOWED_USER_ID=123456789   # your personal Telegram user ID only
HEVY_API_KEY=...
CRONOMETER_API_KEY=...               # TBD — check Cronometer API docs
INTERNAL_SECRET=...                  # shared secret between pg_cron and FastAPI
```

---

## Database Schema

### Tables

```sql
daily_logs          -- manual Telegram input (weight, sleep, energy, stress, notes)
workouts            -- pulled from Hevy API (hevy_id as upsert key)
nutrition_logs      -- pulled from Cronometer API
body_comp_scans     -- manual Evolt scan entry (quarterly)
ai_insights         -- every Claude prompt + response stored (for audit + context)
rolling_state       -- single-row living memory JSON document
summary_embeddings  -- vector(1536) embeddings of weekly summaries for semantic search
job_runs            -- log of every pg_cron job execution (success/error/duration)
```

### Materialised Views

```sql
weekly_summaries    -- weekly aggregates across all pillars, refreshed nightly
monthly_summaries   -- monthly aggregates, refreshed nightly
```

### Key Functions

```sql
get_rolling_state()                          -- returns current rolling_state jsonb
upsert_rolling_state(new_state jsonb)        -- replaces rolling state row
get_week_data(p_week_start date)             -- full week raw data as jsonb
match_summaries(embedding, threshold, count) -- pgvector similarity search
```

### pg_cron Jobs (all times SGT = UTC+8)

| Job | Schedule | What it does |
|---|---|---|
| `refresh-mat-views` | 1am daily | Refreshes weekly/monthly materialised views via SQL |
| `sync-hevy` | 11pm daily | POST /jobs/sync-hevy |
| `sync-cronometer` | 11:05pm daily | POST /jobs/sync-cronometer |
| `daily-nudge` | 8am daily | POST /jobs/daily-nudge |
| `weekly-review` | 8pm Sunday | POST /jobs/weekly-review |

pg_cron jobs use `current_setting('app.api_base_url')` and `current_setting('app.internal_secret')`.
These are set via:
```sql
ALTER DATABASE postgres SET app.api_base_url   = 'https://your-app.railway.app';
ALTER DATABASE postgres SET app.internal_secret = 'your-secret';
```

---

## System Architecture

```
INPUT LAYER
  Telegram Bot       → POST /ingest/telegram  (NLP parsed by Claude)
  Hevy API           → POST /jobs/sync-hevy   (pg_cron triggered)
  Cronometer API     → POST /jobs/sync-cronometer (pg_cron triggered)
  Manual (Evolt)     → POST /ingest/evolt

BACKEND (FastAPI on Railway)
  /ingest/*          → normalise → validate → upsert → ack
  /jobs/*            → protected by internal_secret header
  /query/*           → ad hoc queries, used by /ask Telegram command

DATABASE (Supabase)
  Raw tables → nightly pg_cron → materialised views
  pg_cron fires HTTP POSTs to Railway for AI jobs
  mat view refresh runs as pure SQL inside pg_cron (no HTTP)

AI LAYER (Claude API)
  Context builder assembles token-budgeted prompt:
    always:  rolling_state (~800t)
    weekly:  this week raw + 4 week aggs + 6 month aggs + all Evolt + last 2 insights
    daily:   yesterday log + this week so far
    ad hoc:  vector search results (top 5 matching summaries)

OUTPUT
  Telegram message   → primary interface
  Next.js dashboard  → charts, history browser (later phase)
```

---

## AI Layer Design

### Context Budget per Query Type

```
WEEKLY REVIEW (~6k tokens total)
  rolling_state                    ~800t
  this week raw (get_week_data())  ~1400t
  last 4 weekly_summaries          ~600t
  last 6 monthly_summaries         ~400t
  all body_comp_scans              ~300t
  last 2 ai_insights               ~1200t
  system prompt + instructions     ~300t

DAILY NUDGE (~2k tokens total)
  rolling_state                    ~800t
  yesterday daily_log              ~150t
  this week logs so far            ~300t
  instruction                      ~100t

AD HOC /ask (~4k tokens total)
  rolling_state                    ~800t
  vector search results (top 5)    ~1500t
  user question                    ~100t
```

### Rolling State Schema

```json
{
  "last_updated": "2024-01-21",
  "goals": {
    "primary": "recomp — lose 5kg fat, gain 2kg muscle",
    "target_date": "2024-06-01",
    "current_trajectory": "on track"
  },
  "trends": {
    "weight": "down 0.3kg/week avg last 6 weeks",
    "strength": "bench +5kg last 8 weeks",
    "sleep": "consistently poor Sun-Mon",
    "nutrition": "protein avg 140g, 20g short of target"
  },
  "known_patterns": [
    "High stress weeks correlate with skipped sessions",
    "Sleep quality drops when training 5+ days/week",
    "Weight spikes Friday-Saturday (social eating)"
  ],
  "active_recommendations": [
    { "rec": "Increase protein to 160g", "since": "2024-01-15", "status": "in progress" }
  ],
  "flags": [
    { "flag": "No deload in 10 weeks", "severity": "high" }
  ]
}
```

### Weekly Review Flow

```
1. Assemble context (context_builder.py)
2. Call Claude → get review text
3. Store full prompt + response in ai_insights
4. Second Claude call: rolling_state + review → updated rolling_state JSON
5. Upsert rolling_state
6. Send review to Telegram (chunked if >4000 chars)
```

---

## Telegram Bot Commands

```
(plain message)     → NLP parse → upsert daily_log
/week               → trigger weekly review on demand
/ask <question>     → ad hoc query against data
/evolt              → guided Evolt scan entry flow
/status             → today's log so far
/jobs               → show last 5 job_runs (debug)
```

### NLP Parsing Pattern

Raw Telegram message → Claude API (structured extraction) → dict → upsert

```python
system = """Extract health metrics from the user message.
Return JSON only. Keys (all optional):
weight_kg, sleep_hrs, sleep_qual (1-10), energy (1-10), stress (1-10), notes.
Omit keys not mentioned."""

# Handles all of:
# "slept 7.5, felt good, 74.1kg"
# "weight 73.8, sleep was trash maybe 5hrs, stress 8"
# "8 hours, energy solid"
```

---

## Job Endpoint Pattern

All `/jobs/*` endpoints follow this pattern:

```python
@router.post("/jobs/{job_name}")
async def run_job(job_name: str, request: Request):
    # 1. Verify internal_secret header
    # 2. Log job start to job_runs
    # 3. Do the work (idempotent — safe to run twice)
    # 4. Log result (success/error + duration_ms) to job_runs
    # 5. Return { status, message }
```

Jobs must be **idempotent** — pg_cron fire-and-forget means no retry logic,
so the job itself must be safe to re-run (use upserts, not inserts).

---

## Deployment

```
Railway
  healthos-api    → FastAPI (always on, handles webhooks + job endpoints)
  healthos-bot    → Telegram bot (always on, long polling)

Supabase
  Postgres + pgvector + pg_cron + pg_net

Vercel
  Next.js dashboard (later phase)

Migrations
  Supabase project is connected to this GitHub repo via supabase.com dashboard.
  Migrations are applied automatically on push to main — no GitHub Actions needed.
```

---

## Migration Workflow

```bash
# Create new migration
supabase migration new <name>
# edit supabase/migrations/<timestamp>_<name>.sql

# Test locally
supabase db reset --local

# Deploy: push to main → Supabase GitHub integration applies automatically
git add . && git commit -m "migration: <name>" && git push origin main
```

---

## Data Sources

| Pillar | Source | Method |
|---|---|---|
| Training | Hevy | API polling (daily) |
| Nutrition | Cronometer | API polling (daily) |
| Sleep | Manual | Telegram NLP |
| Weight | Manual | Telegram NLP |
| Body comp | Evolt scans | Manual entry via /evolt command |
| Subjective | Manual | Telegram NLP (energy, stress, notes) |

---

## What Has Been Done

- [x] Full architecture designed
- [x] Database schema written (supabase/migrations/20240101000000_initial_schema.sql)
- [x] Supabase CLI migration workflow designed (GitHub integration handles auto-deploy)

## What Needs To Be Built (in order)

1. [ ] Repo init + supabase init + apply schema via migration
2. [ ] FastAPI skeleton (main.py, config.py, db/client.py)
3. [ ] job_runs migration + add to schema
4. [ ] Telegram bot — NLP logging, /week, /ask, /evolt commands
5. [ ] POST /ingest/telegram route
6. [ ] POST /jobs/sync-hevy
7. [ ] POST /jobs/sync-cronometer
8. [ ] POST /jobs/daily-nudge
9. [ ] POST /jobs/weekly-review (most complex — includes rolling state update)
10. [ ] context_builder.py
11. [ ] rolling_state.py
12. [ ] Deploy to Railway
13. [ ] Set app.api_base_url and app.internal_secret in Supabase
14. [ ] Next.js dashboard (later phase)
