-- Evening nutrition nudge at 9pm SGT (1pm UTC)
SELECT cron.schedule(
  'nutrition-nudge',
  '0 13 * * *',
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
