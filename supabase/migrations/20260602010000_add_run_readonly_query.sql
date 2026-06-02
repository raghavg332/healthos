-- Safe read-only SQL execution for the /ask text-to-SQL agent.
--
-- Wrapping the caller's query in `SELECT ... FROM (<query>) t` means only a
-- single SELECT can ever execute — INSERT/UPDATE/DELETE/DDL cannot appear in a
-- subquery position and will raise a syntax error before anything runs.
-- A 5s statement timeout caps runaway queries. Single-user app, service role only.

create or replace function run_readonly_query(query text)
returns jsonb
language plpgsql
as $$
declare
  result jsonb;
begin
  execute format(
    'select coalesce(jsonb_agg(t), ''[]''::jsonb) from (%s) as t',
    query
  ) into result;
  return result;
end;
$$;

alter function run_readonly_query(text) set statement_timeout = '5s';
