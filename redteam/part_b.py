"""Part B: what each restricted login can do directly. One statement per transaction, always ROLLED BACK.
Connects only with HQ_READER_URL / HQ_SERVICE_URL / HQ_LOG_URL (never DATABASE_URL). Never prints a URL."""
import json
import os
import time
from pathlib import Path

import psycopg
from dotenv import dotenv_values

env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
LOGINS = {"hq_reader": env["HQ_READER_URL"], "hq_service": env["HQ_SERVICE_URL"], "hq_logger": env["HQ_LOG_URL"]}

# (label, [statements run in ONE transaction, last one is reported], mode)
# mode "rows": report row count + short preview (summarised, not raw secrets); "val": single value
ACTIONS = [
    ("who am i", ["select current_user, session_user, current_database()"]),
    ("version()", ["select version()"]),
    ("show statement_timeout", ["show statement_timeout"]),
    ("show default_transaction_read_only", ["show default_transaction_read_only"]),
    ("show search_path", ["show search_path"]),
    ("read hq.hospitals", ["select count(*) from hq.hospitals"]),
    ("read hq.measure_values", ["select count(*) from hq.measure_values"]),
    ("read hq.measures", ["select count(*) from hq.measures"]),
    ("read hq.v_scorecard", ["select count(*) from hq.v_scorecard"]),
    ("list tables in hq via pg_class", ["select count(*), string_agg(relname, ',' order by relname) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='hq' and c.relkind in ('r','v','m')"]),
    ("read hq_app.request_log", ["select count(*) from hq_app.request_log"]),
    ("read hq_app.request_log.question", ["select question from hq_app.request_log order by id desc limit 3"]),
    ("read hq_app.alert_log", ["select count(*) from hq_app.alert_log"]),
    ("read hq_docs.chunks", ["select count(*) from hq_docs.chunks"]),
    ("read hq_docs.chunks.body", ["select left(body,30) from hq_docs.chunks limit 1"]),
    ("insert hq_app.request_log", ["insert into hq_app.request_log(question) values ('redteam probe')"]),
    ("insert hq.hospitals", ["insert into hq.hospitals(facility_id) values ('RT')"]),
    ("update hq.hospitals", ["update hq.hospitals set state='XX' where false"]),
    ("delete hq.hospitals", ["delete from hq.hospitals where false"]),
    ("create temp table", ["create temp table rt_t(a int)"]),
    ("create table in hq", ["create table hq.rt_t(a int)"]),
    ("create table in public", ["create table public.rt_t(a int)"]),
    ("create schema", ["create schema rt_s"]),
    ("information_schema.tables", ["select count(*) from information_schema.tables"]),
    ("information_schema.tables (names)", ["select string_agg(table_schema||'.'||table_name, ',') from (select * from information_schema.tables where table_schema not in ('pg_catalog','information_schema') order by 1,2 limit 60) s"]),
    ("pg_roles (count)", ["select count(*) from pg_roles"]),
    ("pg_roles (names)", ["select string_agg(rolname, ',' order by rolname) from pg_roles"]),
    ("pg_authid", ["select count(*) from pg_authid"]),
    ("pg_shadow", ["select count(*) from pg_shadow"]),
    ("pg_user", ["select count(*) from pg_user"]),
    ("pg_stat_activity (rows)", ["select count(*) from pg_stat_activity"]),
    ("pg_stat_activity (other sessions' query text visible?)", ["select count(*) filter (where usename is distinct from current_user and query not in ('<insufficient privilege>','')), count(*) filter (where usename is distinct from current_user), count(distinct usename) from pg_stat_activity"]),
    ("pg_stat_activity (other users' names)", ["select string_agg(distinct usename, ',') from pg_stat_activity"]),
    ("pg_stat_statements", ["select count(*) from pg_stat_statements"]),
    ("pg_settings (count)", ["select count(*) from pg_settings"]),
    ("pg_settings (sensitive-ish values visible?)", ["select name, case when setting is null then 'null' else 'present' end from pg_settings where name in ('data_directory','config_file','hba_file','ssl_key_file','log_directory') order by 1"]),
    ("current_setting statement_timeout", ["select current_setting('statement_timeout')"]),
    ("current_setting data_directory", ["select current_setting('data_directory', true)"]),
    ("current_setting is_superuser", ["select current_setting('is_superuser')"]),
    ("current_setting app/jwt-ish", ["select current_setting('app.settings.jwt_secret', true)"]),
    ("pg_read_file", ["select pg_read_file('/etc/passwd')"]),
    ("pg_ls_dir", ["select pg_ls_dir('.')"]),
    ("pg_ls_logdir", ["select count(*) from pg_ls_logdir()"]),
    ("pg_read_server_files role member?", ["select pg_has_role(current_user,'pg_read_server_files','member'), pg_has_role(current_user,'pg_monitor','member'), pg_has_role(current_user,'pg_read_all_settings','member'), pg_has_role(current_user,'pg_read_all_stats','member')"]),
    ("lo_import", ["select lo_import('/etc/passwd')"]),
    ("lo_from_bytea (create large object)", ["select lo_from_bytea(0,'abc')"]),
    ("lo_creat", ["select lo_creat(-1)"]),
    ("dblink ext installed?", ["select count(*) from pg_extension where extname in ('dblink','postgres_fdw','file_fdw','plpython3u','plperlu')"]),
    ("extensions list", ["select string_agg(extname,',' order by extname) from pg_extension"]),
    ("query_to_xml on request_log", ["select query_to_xml('select question from hq_app.request_log limit 1', true, false, '')"]),
    ("table_to_xml on request_log", ["select table_to_xml('hq_app.request_log', true, false, '')"]),
    ("table_to_xml on hq.measures (control)", ["select length(table_to_xml('hq.measures', true, false, '')::text)"]),
    ("advisory lock", ["select pg_advisory_xact_lock(424242)"]),
    ("pg_terminate_backend(own other pid=0)", ["select pg_terminate_backend(2147483000)"]),
    ("pg_cancel_backend(nonexistent)", ["select pg_cancel_backend(2147483000)"]),
    ("auth schema", ["select count(*) from auth.users"]),
    ("auth schema usage?", ["select has_schema_privilege('auth','usage')"]),
    ("vault schema", ["select count(*) from vault.secrets"]),
    ("vault.decrypted_secrets", ["select count(*) from vault.decrypted_secrets"]),
    ("storage schema", ["select count(*) from storage.objects"]),
    ("extensions schema functions", ["select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='extensions'"]),
    ("schema usage matrix", ["select string_agg(nspname||'='||has_schema_privilege(nspname,'usage')::text, ',' order by nspname) from pg_namespace where nspname !~ '^pg_toast|^pg_temp'"]),
    ("public schema create?", ["select has_schema_create_privilege('public','create') , has_schema_privilege('public','usage')"]),
    ("set statement_timeout=0 then show", ["set statement_timeout = 0", "show statement_timeout"]),
    ("set local statement_timeout=0 then show", ["set local statement_timeout = 0", "show statement_timeout"]),
    ("set_config statement_timeout=0 then show", ["select set_config('statement_timeout','0',true)", "show statement_timeout"]),
    ("set transaction read write", ["set transaction read write", "show transaction_read_only"]),
    ("set default_transaction_read_only off then rw?", ["set default_transaction_read_only = off", "set transaction read write", "show transaction_read_only"]),
    ("set_config read_only off", ["select set_config('transaction_read_only','off',true)", "show transaction_read_only"]),
    ("set role postgres", ["set role postgres", "select current_user"]),
    ("set role hq_logger", ["set role hq_logger", "select current_user"]),
    ("set session authorization postgres", ["set session authorization postgres", "select current_user"]),
    ("set search_path hq_app then read", ["set search_path = hq_app", "select count(*) from request_log"]),
]


def run_one(url, stmts, timeout_s=60):
    t0 = time.perf_counter()
    conn = None
    try:
        conn = psycopg.connect(url, autocommit=False, connect_timeout=30)
        cur = conn.cursor()
        res = None
        for s in stmts:
            cur.execute(s)
            try:
                res = cur.fetchall()
            except psycopg.ProgrammingError:
                res = "ok(no rows)"
        out = ("ALLOWED", repr(res)[:300])
    except psycopg.Error as e:
        out = ("DENIED/ERR", f"{type(e).__name__}: {str(e).strip().splitlines()[0][:160]}")
    except Exception as e:  # noqa
        out = ("ERR", f"{type(e).__name__}: {str(e)[:160]}")
    finally:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass
    return out[0], out[1], round(time.perf_counter() - t0, 2)


def main():
    rows = []
    for login, url in LOGINS.items():
        for label, stmts in ACTIONS:
            status, detail, secs = run_one(url, stmts)
            rows.append({"login": login, "action": label, "status": status, "detail": detail, "secs": secs})
            print(f"{login:10s} | {label[:48]:48s} | {status:10s} | {detail[:150]}", flush=True)
    Path(__file__).with_name("part_b_results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")


main()
