-- Update cron schedules and add daily-nudge-retry
-- All times UTC (SGT = UTC+8)

-- Hevy sync: 3am SGT = 7pm UTC
SELECT cron.unschedule('sync-hevy');
SELECT cron.schedule(
  'sync-hevy',
  '0 19 * * *',
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

-- Nutrition nudge: 11pm SGT = 3pm UTC
SELECT cron.unschedule('nutrition-nudge');
SELECT cron.schedule(
  'nutrition-nudge',
  '0 15 * * *',
  $$
    SELECT net.http_post(
      url     := current_setting('app.api_base_url') || '/jobs/nutrition-nudge',
      headers := jsonb_build_object(
        'Content-Type',  'application/json',
        'Authorization', 'Bearer ' || current_setting('app.internal_secret')
      ),
      body    := '{}'
    );
  $$
);

-- Mat view refresh: 5am SGT = 9pm UTC
SELECT cron.unschedule('refresh-mat-views');
SELECT cron.schedule(
  'refresh-mat-views',
  '0 21 * * *',
  $$
    REFRESH MATERIALIZED VIEW CONCURRENTLY weekly_summaries;
    REFRESH MATERIALIZED VIEW CONCURRENTLY monthly_summaries;
  $$
);

-- Daily nudge retry: 12pm SGT = 4am UTC (new)
SELECT cron.schedule(
  'daily-nudge-retry',
  '0 4 * * *',
  $$
    SELECT net.http_post(
      url     := current_setting('app.api_base_url') || '/jobs/daily-nudge-retry',
      headers := jsonb_build_object(
        'Content-Type',  'application/json',
        'Authorization', 'Bearer ' || current_setting('app.internal_secret')
      ),
      body    := '{}'
    );
  $$
);
