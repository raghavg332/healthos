-- Reschedule all cron jobs with hardcoded URL and secret
-- Replace ,w] with your actual secret before committing

-- Remove existing jobs
SELECT cron.unschedule('sync-hevy');
SELECT cron.unschedule('sync-cronometer');
SELECT cron.unschedule('daily-nudge');
SELECT cron.unschedule('nutrition-nudge');
SELECT cron.unschedule('refresh-mat-views');

-- Hevy sync: 3am SGT = 7pm UTC
SELECT cron.schedule(
  'sync-hevy',
  '0 19 * * *',
  $$
    SELECT net.http_post(
      url     := 'https://worker-production-4578.up.railway.app/jobs/sync-hevy',
      headers := '{"Content-Type": "application/json", "Authorization": "Bearer ,w]"}'::jsonb,
      body    := '{}'
    );
  $$
);

-- Cronometer sync: 11:05pm SGT = 3:05pm UTC
SELECT cron.schedule(
  'sync-cronometer',
  '5 15 * * *',
  $$
    SELECT net.http_post(
      url     := 'https://worker-production-4578.up.railway.app/jobs/sync-cronometer',
      headers := '{"Content-Type": "application/json", "Authorization": "Bearer ,w]"}'::jsonb,
      body    := '{}'
    );
  $$
);

-- Daily nudge: 8am SGT = midnight UTC
SELECT cron.schedule(
  'daily-nudge',
  '0 0 * * *',
  $$
    SELECT net.http_post(
      url     := 'https://worker-production-4578.up.railway.app/jobs/daily-nudge',
      headers := '{"Content-Type": "application/json", "Authorization": "Bearer ,w]"}'::jsonb,
      body    := '{}'
    );
  $$
);

-- Daily nudge retry: 12pm SGT = 4am UTC
SELECT cron.schedule(
  'daily-nudge-retry',
  '0 4 * * *',
  $$
    SELECT net.http_post(
      url     := 'https://worker-production-4578.up.railway.app/jobs/daily-nudge-retry',
      headers := '{"Content-Type": "application/json", "Authorization": "Bearer ,w]"}'::jsonb,
      body    := '{}'
    );
  $$
);

-- Nutrition nudge: 11pm SGT = 3pm UTC
SELECT cron.schedule(
  'nutrition-nudge',
  '0 15 * * *',
  $$
    SELECT net.http_post(
      url     := 'https://worker-production-4578.up.railway.app/jobs/nutrition-nudge',
      headers := '{"Content-Type": "application/json", "Authorization": "Bearer ,w]"}'::jsonb,
      body    := '{}'
    );
  $$
);

-- Weekly review: 8pm SGT Sunday = noon UTC Sunday
SELECT cron.schedule(
  'weekly-review',
  '0 12 * * 0',
  $$
    SELECT net.http_post(
      url     := 'https://worker-production-4578.up.railway.app/jobs/weekly-review',
      headers := '{"Content-Type": "application/json", "Authorization": "Bearer ,w]"}'::jsonb,
      body    := '{}'
    );
  $$
);

-- Mat view refresh: 5am SGT = 9pm UTC
SELECT cron.schedule(
  'refresh-mat-views',
  '0 21 * * *',
  $$
    REFRESH MATERIALIZED VIEW CONCURRENTLY weekly_summaries;
    REFRESH MATERIALIZED VIEW CONCURRENTLY monthly_summaries;
  $$
);
