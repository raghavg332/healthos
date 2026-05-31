-- ============================================================
-- HealthOS — Supabase Schema
-- Run this entire file in Supabase SQL Editor
-- ============================================================


-- ============================================================
-- EXTENSIONS
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;       -- pgvector for embeddings
CREATE EXTENSION IF NOT EXISTS pg_cron;      -- scheduled jobs
CREATE EXTENSION IF NOT EXISTS pg_net;       -- HTTP calls from pg_cron


-- ============================================================
-- CORE TABLES
-- ============================================================

-- Daily manual log (via Telegram)
CREATE TABLE IF NOT EXISTS daily_logs (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  date         date        NOT NULL UNIQUE,
  weight_kg    numeric(5,2),
  sleep_hrs    numeric(4,2),
  sleep_qual   int         CHECK (sleep_qual BETWEEN 1 AND 10),
  energy       int         CHECK (energy BETWEEN 1 AND 10),
  stress       int         CHECK (stress BETWEEN 1 AND 10),
  notes        text,
  raw_input    text,                          -- original Telegram message
  created_at   timestamptz DEFAULT now(),
  updated_at   timestamptz DEFAULT now()
);

-- Workouts pulled from Hevy API
CREATE TABLE IF NOT EXISTS workouts (
  id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  hevy_id        text        UNIQUE NOT NULL,
  date           date        NOT NULL,
  title          text,
  duration_mins  int,
  volume_kg      numeric(10,2),              -- total tonnage for the session
  exercises      jsonb,                      -- full Hevy exercise/set payload
  created_at     timestamptz DEFAULT now()
);

-- Nutrition pulled from Cronometer API
CREATE TABLE IF NOT EXISTS nutrition_logs (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  date        date        NOT NULL UNIQUE,
  calories    numeric(7,2),
  protein_g   numeric(6,2),
  carbs_g     numeric(6,2),
  fat_g       numeric(6,2),
  fibre_g     numeric(5,2),
  micros      jsonb,                         -- full micronutrient breakdown
  created_at  timestamptz DEFAULT now(),
  updated_at  timestamptz DEFAULT now()
);

-- Evolt body composition scans (quarterly)
CREATE TABLE IF NOT EXISTS body_comp_scans (
  id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_date       date        NOT NULL,
  weight_kg       numeric(5,2),
  body_fat_pct    numeric(5,2),
  muscle_mass_kg  numeric(5,2),
  visceral_fat    numeric(5,2),
  bmr             int,                       -- basal metabolic rate (kcal)
  bmi             numeric(5,2),
  raw_data        jsonb,                     -- full Evolt export if available
  notes           text,
  created_at      timestamptz DEFAULT now()
);

-- AI-generated insights (every prompt + response stored)
CREATE TABLE IF NOT EXISTS ai_insights (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  insight_type  text        NOT NULL,        -- 'weekly_review' | 'daily_nudge' | 'ad_hoc' | 'body_comp'
  period_start  date,
  period_end    date,
  prompt        text,
  response      text,
  model         text,
  prompt_tokens int,
  output_tokens int,
  created_at    timestamptz DEFAULT now()
);

-- Rolling state — single-row living memory document
-- Always upserted, never appended
CREATE TABLE IF NOT EXISTS rolling_state (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  state       jsonb       NOT NULL,
  updated_at  timestamptz DEFAULT now()
);

-- Seed with empty rolling state so the row always exists
INSERT INTO rolling_state (state) VALUES ('{
  "last_updated": null,
  "goals": {
    "primary": null,
    "target_date": null,
    "current_trajectory": null
  },
  "trends": {
    "weight": null,
    "strength": null,
    "sleep": null,
    "nutrition": null
  },
  "known_patterns": [],
  "active_recommendations": [],
  "flags": []
}'::jsonb)
ON CONFLICT DO NOTHING;

-- Job execution log
CREATE TABLE IF NOT EXISTS job_runs (
  id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  job_name     text        NOT NULL,
  status       text        NOT NULL CHECK (status IN ('started', 'success', 'error')),
  message      text,
  duration_ms  int,
  created_at   timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_job_runs_name_created ON job_runs (job_name, created_at DESC);

-- Weekly summary embeddings for vector search
CREATE TABLE IF NOT EXISTS summary_embeddings (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  week        date        NOT NULL UNIQUE,
  summary     text,
  embedding   vector(1536),
  created_at  timestamptz DEFAULT now()
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_daily_logs_date        ON daily_logs (date DESC);
CREATE INDEX IF NOT EXISTS idx_workouts_date          ON workouts (date DESC);
CREATE INDEX IF NOT EXISTS idx_workouts_hevy_id       ON workouts (hevy_id);
CREATE INDEX IF NOT EXISTS idx_nutrition_logs_date    ON nutrition_logs (date DESC);
CREATE INDEX IF NOT EXISTS idx_body_comp_scan_date    ON body_comp_scans (scan_date DESC);
CREATE INDEX IF NOT EXISTS idx_ai_insights_type       ON ai_insights (insight_type, created_at DESC);

-- IVFFlat index for approximate nearest-neighbour vector search
CREATE INDEX IF NOT EXISTS idx_embeddings_vector
  ON summary_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 50);                         -- tune lists as data grows


-- ============================================================
-- UPDATED_AT TRIGGER
-- ============================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_daily_logs_updated_at
  BEFORE UPDATE ON daily_logs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_nutrition_logs_updated_at
  BEFORE UPDATE ON nutrition_logs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- ============================================================
-- MATERIALISED VIEWS
-- ============================================================

-- Weekly aggregates — refreshed nightly by pg_cron
CREATE MATERIALIZED VIEW IF NOT EXISTS weekly_summaries AS
SELECT
  date_trunc('week', dl.date)::date            AS week,

  -- Weight
  ROUND(AVG(dl.weight_kg)::numeric, 2)         AS avg_weight,
  MIN(dl.weight_kg)                            AS min_weight,
  MAX(dl.weight_kg)                            AS max_weight,

  -- Sleep
  ROUND(AVG(dl.sleep_hrs)::numeric, 2)         AS avg_sleep_hrs,
  ROUND(AVG(dl.sleep_qual)::numeric, 1)        AS avg_sleep_qual,

  -- Subjective
  ROUND(AVG(dl.energy)::numeric, 1)            AS avg_energy,
  ROUND(AVG(dl.stress)::numeric, 1)            AS avg_stress,
  COUNT(dl.id)                                 AS days_logged,

  -- Nutrition
  ROUND(AVG(nl.calories)::numeric, 0)          AS avg_calories,
  ROUND(AVG(nl.protein_g)::numeric, 1)         AS avg_protein,
  ROUND(AVG(nl.carbs_g)::numeric, 1)           AS avg_carbs,
  ROUND(AVG(nl.fat_g)::numeric, 1)             AS avg_fat,
  COUNT(nl.id)                                 AS days_nutrition_logged,

  -- Training
  COUNT(w.id)                                  AS workout_count,
  COALESCE(SUM(w.volume_kg), 0)                AS total_volume_kg,
  ROUND(AVG(w.duration_mins)::numeric, 0)      AS avg_workout_duration_mins

FROM daily_logs dl
LEFT JOIN nutrition_logs nl ON nl.date = dl.date
LEFT JOIN workouts w        ON w.date  = dl.date
GROUP BY 1
ORDER BY 1 DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_weekly_summaries_week
  ON weekly_summaries (week);


-- Monthly aggregates — refreshed nightly by pg_cron
CREATE MATERIALIZED VIEW IF NOT EXISTS monthly_summaries AS
SELECT
  date_trunc('month', dl.date)::date           AS month,

  -- Weight
  ROUND(AVG(dl.weight_kg)::numeric, 2)         AS avg_weight,
  ROUND((MAX(dl.weight_kg) - MIN(dl.weight_kg))::numeric, 2) AS weight_variance,

  -- Sleep & recovery
  ROUND(AVG(dl.sleep_hrs)::numeric, 2)         AS avg_sleep_hrs,
  ROUND(AVG(dl.energy)::numeric, 1)            AS avg_energy,
  ROUND(AVG(dl.stress)::numeric, 1)            AS avg_stress,

  -- Nutrition
  ROUND(AVG(nl.calories)::numeric, 0)          AS avg_calories,
  ROUND(AVG(nl.protein_g)::numeric, 1)         AS avg_protein,

  -- Training
  COUNT(DISTINCT w.id)                         AS workout_count,
  COALESCE(SUM(w.volume_kg), 0)                AS total_volume_kg

FROM daily_logs dl
LEFT JOIN nutrition_logs nl ON nl.date = dl.date
LEFT JOIN workouts w        ON w.date  = dl.date
GROUP BY 1
ORDER BY 1 DESC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_monthly_summaries_month
  ON monthly_summaries (month);


-- ============================================================
-- FUNCTIONS
-- ============================================================

-- Vector similarity search over weekly summaries
CREATE OR REPLACE FUNCTION match_summaries(
  query_embedding  vector(1536),
  match_threshold  float   DEFAULT 0.7,
  match_count      int     DEFAULT 5
)
RETURNS TABLE (
  week        date,
  summary     text,
  similarity  float
)
LANGUAGE sql STABLE AS $$
  SELECT
    week,
    summary,
    1 - (embedding <=> query_embedding) AS similarity
  FROM summary_embeddings
  WHERE 1 - (embedding <=> query_embedding) > match_threshold
  ORDER BY similarity DESC
  LIMIT match_count;
$$;

-- Convenience: get rolling state as jsonb (always single row)
CREATE OR REPLACE FUNCTION get_rolling_state()
RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT state FROM rolling_state ORDER BY updated_at DESC LIMIT 1;
$$;

-- Upsert rolling state (replaces the single row)
CREATE OR REPLACE FUNCTION upsert_rolling_state(new_state jsonb)
RETURNS void
LANGUAGE sql AS $$
  UPDATE rolling_state SET state = new_state, updated_at = now();
$$;

-- Get week summary as a flat jsonb for easy LLM serialisation
CREATE OR REPLACE FUNCTION get_week_data(p_week_start date)
RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT jsonb_build_object(
    'week_start',       p_week_start,
    'daily_logs',       (
      SELECT jsonb_agg(row_to_json(dl) ORDER BY dl.date)
      FROM daily_logs dl
      WHERE dl.date BETWEEN p_week_start AND p_week_start + 6
    ),
    'workouts',         (
      SELECT jsonb_agg(row_to_json(w) ORDER BY w.date)
      FROM workouts w
      WHERE w.date BETWEEN p_week_start AND p_week_start + 6
    ),
    'nutrition',        (
      SELECT jsonb_agg(row_to_json(nl) ORDER BY nl.date)
      FROM nutrition_logs nl
      WHERE nl.date BETWEEN p_week_start AND p_week_start + 6
    )
  );
$$;


-- ============================================================
-- pg_cron JOBS
-- (all times UTC — SGT is UTC+8)
-- ============================================================

-- Refresh materialised views nightly at 1am SGT (5pm UTC)
SELECT cron.schedule(
  'refresh-mat-views',
  '0 17 * * *',
  $$
    REFRESH MATERIALIZED VIEW CONCURRENTLY weekly_summaries;
    REFRESH MATERIALIZED VIEW CONCURRENTLY monthly_summaries;
  $$
);

-- Trigger Hevy sync nightly at 11pm SGT (3pm UTC)
SELECT cron.schedule(
  'sync-hevy',
  '0 15 * * *',
  $$
    SELECT net.http_post(
      url     := current_setting('app.api_base_url') || '/jobs/sync-hevy',
      headers := jsonb_build_object(
        'Content-Type',  'application/json',
        'Authorization', 'Bearer ' || current_setting('app.internal_secret')
      ),
      body    := '{}'
    );
  $$
);

-- Trigger Cronometer sync nightly at 11pm SGT (3pm UTC)
SELECT cron.schedule(
  'sync-cronometer',
  '5 15 * * *',
  $$
    SELECT net.http_post(
      url     := current_setting('app.api_base_url') || '/jobs/sync-cronometer',
      headers := jsonb_build_object(
        'Content-Type',  'application/json',
        'Authorization', 'Bearer ' || current_setting('app.internal_secret')
      ),
      body    := '{}'
    );
  $$
);

-- Daily nudge at 8am SGT (midnight UTC)
SELECT cron.schedule(
  'daily-nudge',
  '0 0 * * *',
  $$
    SELECT net.http_post(
      url     := current_setting('app.api_base_url') || '/jobs/daily-nudge',
      headers := jsonb_build_object(
        'Content-Type',  'application/json',
        'Authorization', 'Bearer ' || current_setting('app.internal_secret')
      ),
      body    := '{}'
    );
  $$
);

-- Weekly review every Sunday at 8pm SGT (noon UTC)
SELECT cron.schedule(
  'weekly-review',
  '0 12 * * 0',
  $$
    SELECT net.http_post(
      url     := current_setting('app.api_base_url') || '/jobs/weekly-review',
      headers := jsonb_build_object(
        'Content-Type',  'application/json',
        'Authorization', 'Bearer ' || current_setting('app.internal_secret')
      ),
      body    := '{}'
    );
  $$
);


-- ============================================================
-- APP SETTINGS
-- Set these after deployment — replace placeholder values
-- Run in Supabase SQL editor once your Railway URL is known
-- ============================================================

-- ALTER DATABASE postgres SET app.api_base_url  = 'https://your-app.railway.app';
-- ALTER DATABASE postgres SET app.internal_secret = 'your-internal-secret-here';


-- ============================================================
-- ROW LEVEL SECURITY
-- Single-user app — lock everything down to service role only
-- (no public access, no anon access)
-- ============================================================

ALTER TABLE daily_logs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE workouts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE nutrition_logs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE body_comp_scans    ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_insights        ENABLE ROW LEVEL SECURITY;
ALTER TABLE rolling_state      ENABLE ROW LEVEL SECURITY;
ALTER TABLE summary_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE job_runs           ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS by default in Supabase — no extra policy needed.
-- If you add a dashboard with anon/user JWT auth later, add policies here.


-- ============================================================
-- VERIFICATION QUERIES
-- Run these after applying the schema to confirm everything
-- is set up correctly
-- ============================================================

-- Check all tables exist
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'daily_logs', 'workouts', 'nutrition_logs',
    'body_comp_scans', 'ai_insights', 'rolling_state',
    'summary_embeddings', 'job_runs'
  )
ORDER BY table_name;

-- Check materialised views
SELECT matviewname
FROM pg_matviews
WHERE schemaname = 'public';

-- Check pg_cron jobs
SELECT jobname, schedule, command
FROM cron.job
ORDER BY jobname;

-- Check rolling state was seeded
SELECT state FROM rolling_state;