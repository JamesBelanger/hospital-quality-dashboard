"""A+B bridge: send validator-ACCEPTED hostile SQL through the real run_sql (guard + hq_reader). Read-only."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.sql_runner import run_sql, GuardRejected, DatabaseError
CASES = [
 "select count(*) from pg_roles, (with pg_roles as (select 1) select 1) s",
 "select rolname from pg_roles, (with pg_roles as (select 1) select 1) s order by 1",
 "select count(*), count(distinct usename) from pg_stat_activity, (with pg_stat_activity as (select 1) select 1) s",
 "select name from pg_settings, (with pg_settings as (select 1) select 1) s where name in ('statement_timeout','server_version')",
 "select count(*) from pg_user, (with pg_user as (select 1) select 1) s",
 "select count(*) from pg_class, (with pg_class as (select 1) select 1) s",
 "select count(*) from request_log, (with request_log as (select 1) select 1) s",
 "select table_to_xml('hq_app.request_log', true, false, '')",
 "select to_regclass('hq_app.request_log'), has_table_privilege('hq_app.request_log','select')",
 "select version(), current_user, current_database(), inet_server_addr()",
 "select lo_get(16384)",
 "select length(repeat('x', 3000000))",
]
for c in CASES:
    t=time.perf_counter()
    try:
        r = run_sql(c); print("RAN", f"{time.perf_counter()-t:.1f}s", c[:90], "=>", r.row_count, "rows", str(r.rows[:6])[:200])
    except GuardRejected as e: print("GUARD", c[:90], str(e))
    except DatabaseError as e: print("DBERR", f"{time.perf_counter()-t:.1f}s", c[:90], str(e)[:120])
