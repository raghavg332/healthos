-- Set app config for pg_cron jobs
-- These must be set via ALTER ROLE on Supabase (ALTER DATABASE is restricted)
ALTER ROLE postgres SET app.api_base_url = 'https://worker-production-4578.up.railway.app';
ALTER ROLE postgres SET app.internal_secret = ',w]';
