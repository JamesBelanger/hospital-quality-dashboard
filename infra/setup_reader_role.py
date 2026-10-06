"""Create the three least-privilege database logins the service uses, and the request-log table.

Second of two independent safeguards for model-written SQL (the first is service/sql_guard.py):
  * role `hq_reader` can SELECT from schema `hq` and nothing else,
  * role `hq_service` can SELECT from `hq_docs.chunks` only (documentation retrieval),
  * every transaction is read-only,
  * statements are cancelled after 5 s (hq_reader) / 10 s (hq_service),
  * role `hq_logger` can INSERT into and SELECT from `hq_app.request_log` and `hq_app.alert_log` and nothing else (5 s timeout).
    The log lives in its own schema `hq_app`, which only that role can use; the other two cannot read it.

Also enables the pgvector extension. Run as the database owner (DATABASE_URL in .env).
Writes HQ_READER_URL, HQ_SERVICE_URL and HQ_LOG_URL to .env; passwords are generated here and never printed.
Safe to re-run: it rotates all three passwords (the log table is created only if missing).
"""
import os
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROLE = "hq_reader"
SERVICE_ROLE = "hq_service"
LOGGER_ROLE = "hq_logger"
ENV = Path(__file__).resolve().parents[1] / ".env"


REQUEST_LOG_DDL = """
create schema if not exists hq_app;
create table if not exists hq_app.request_log (
    id bigserial primary key,
    ts timestamptz not null default now(),
    release text, client_hash text, question text, route text,
    refused boolean, refusal_reason text, sql_text text, row_count int,
    retrieved_chunk_ids text[], cited_chunk_ids text[], prompt_versions jsonb,
    model text, input_tokens int, output_tokens int, cost_usd numeric(10,6),
    latency_ms int, step_ms jsonb, repaired boolean, repair_kind text, error text
);
create index if not exists request_log_ts_idx on hq_app.request_log (ts)
"""

# One row per alert actually raised by ops/alert_check.py; the primary key is what suppresses repeats.
ALERT_LOG_DDL = """
create table if not exists hq_app.alert_log (
    alert_key text not null,
    period text not null,
    fired_at timestamptz not null default now(),
    detail jsonb,
    primary key (alert_key, period)
)"""
ALERT_LOG_GRANT = "grant insert, select on hq_app.alert_log to {}"


def _create_role(cur, name: str, password: str) -> str:
    cur.execute("select 1 from pg_roles where rolname = %s", (name,))
    verb = "alter" if cur.fetchone() else "create"
    cur.execute(sql.SQL("{} role {} login password {}").format(
        sql.SQL(verb), sql.Identifier(name), sql.Literal(password)))
    return verb


def _role_url(owner_url: str, name: str, password: str) -> str:
    # Same host and database as the owner URL; Supabase's pooler wants "<role>.<project-ref>" as the user.
    u = urlsplit(owner_url)
    owner_user = u.username or ""
    user = f"{name}.{owner_user.split('.', 1)[1]}" if "." in owner_user else name
    netloc = f"{quote(user)}:{quote(password)}@{u.hostname}" + (f":{u.port}" if u.port else "")
    return urlunsplit((u.scheme, netloc, u.path, u.query, u.fragment))


def main():
    load_dotenv(ENV)
    owner_url = os.environ["DATABASE_URL"]
    pw = {ROLE: secrets.token_urlsafe(24), SERVICE_ROLE: secrets.token_urlsafe(24),
          LOGGER_ROLE: secrets.token_urlsafe(24)}
    reader, service, logger = sql.Identifier(ROLE), sql.Identifier(SERVICE_ROLE), sql.Identifier(LOGGER_ROLE)

    with psycopg.connect(owner_url, autocommit=True, connect_timeout=20) as conn:
        cur = conn.cursor()
        cur.execute("create extension if not exists vector with schema extensions")
        verbs = {name: _create_role(cur, name, pw[name]) for name in pw}
        for stmt in (
            "alter role {} set default_transaction_read_only = on",
            "alter role {} set statement_timeout = '5s'",
            "alter role {} set search_path = hq",
            "grant usage on schema hq to {}",
            "grant select on all tables in schema hq to {}",
            "alter default privileges in schema hq grant select on tables to {}",
        ):
            cur.execute(sql.SQL(stmt).format(reader))
        # hq_service: documentation chunks only. `extensions` holds the pgvector operators.
        for stmt in (
            "alter role {} set default_transaction_read_only = on",
            "alter role {} set statement_timeout = '10s'",
            "alter role {} set search_path = hq_docs, extensions",
            "grant usage on schema hq_docs to {}",
            "grant usage on schema extensions to {}",
            "grant select on hq_docs.chunks to {}",
        ):
            cur.execute(sql.SQL(stmt).format(service))
        # hq_app.request_log: one row per /ask request. Only hq_logger gets anything here.
        cur.execute(REQUEST_LOG_DDL)
        cur.execute(ALERT_LOG_DDL)
        cur.execute("revoke all on schema hq_app from public")
        cur.execute("revoke all on all tables in schema hq_app from public")
        for stmt in (
            "alter role {} set statement_timeout = '5s'",
            "alter role {} set search_path = hq_app",
            "grant usage on schema hq_app to {}",
            "revoke all on hq_app.request_log from {}",
            "grant insert, select on hq_app.request_log to {}",
            "grant usage on sequence hq_app.request_log_id_seq to {}",
            "revoke all on hq_app.alert_log from {}",
            ALERT_LOG_GRANT,
        ):
            cur.execute(sql.SQL(stmt).format(logger))
        cur.execute("select extversion from pg_extension where extname = 'vector'")
        print("pgvector", cur.fetchone()[0], "|", verbs[ROLE], "role", ROLE, "|", verbs[SERVICE_ROLE], "role", SERVICE_ROLE)

    keys = {"HQ_READER_URL": _role_url(owner_url, ROLE, pw[ROLE]),
            "HQ_SERVICE_URL": _role_url(owner_url, SERVICE_ROLE, pw[SERVICE_ROLE]),
            "HQ_LOG_URL": _role_url(owner_url, LOGGER_ROLE, pw[LOGGER_ROLE])}
    lines = [l for l in ENV.read_text(encoding="utf-8").splitlines()
             if not any(l.startswith(k + "=") for k in keys)]
    lines += [f"{k}={v}" for k, v in keys.items()]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(", ".join(keys), "written to .env")


if __name__ == "__main__":
    main()
