"""The request log (`hq_app.request_log`), written and read as the `hq_logger` login.

The log is the service's only memory: it holds no application state in the process, so the limits in
service/limits.py and the /status page are computed from these rows and survive restarts and scale-to-zero.
`log_request` never raises (a logging failure must not fail the user's request). The read helpers do
raise, and the caller decides what an unreachable log means.
"""
from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from psycopg.types.json import Jsonb

from service import db

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

_INSERT = """
insert into hq_app.request_log
 (release, client_hash, question, route, refused, refusal_reason, sql_text, row_count,
  retrieved_chunk_ids, cited_chunk_ids, prompt_versions, model, input_tokens, output_tokens,
  cost_usd, latency_ms, step_ms, repaired, repair_kind, error, doc_collection)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""


def _url() -> str:
    return os.environ["HQ_LOG_URL"]


def build_row(answer, client_hash: str, release: str, error: str | None = None,
              question: str | None = None, latency_ms: int | None = None) -> tuple:
    """Map an Answer (or None, when ask() raised) to the insert parameters."""
    if answer is None:
        return (release, client_hash, question, None, None, None, None, None, None, None, None, None,
                None, None, None, latency_ms, None, None, None, error, None)
    return (
        release, client_hash, answer.question, answer.route, answer.refused, answer.refusal_reason,
        answer.sql, answer.row_count, answer.retrieved_chunk_ids, [c.chunk_id for c in answer.citations],
        Jsonb(answer.prompt_versions), answer.model, answer.total_input_tokens,
        answer.total_output_tokens, answer.total_cost_usd,
        latency_ms if latency_ms is not None else answer.timings.get("total_ms"),
        Jsonb(answer.timings), answer.repaired, answer.repair_kind, error, answer.doc_collection)


def log_request(answer, client_hash: str, release: str, error: str | None = None,
                question: str | None = None, latency_ms: int | None = None) -> None:
    """Insert one row. `answer` is None when ask() raised (then pass `error`, `question`, `latency_ms`).
    Never raises: on failure it prints one line to stderr."""
    try:
        row = build_row(answer, client_hash, release, error, question, latency_ms)
        db.run(_url(), lambda cur: cur.execute(_INSERT, row))
    except Exception as e:  # noqa: BLE001  (a logging failure must not fail the request)
        print(f"request-log write failed: {type(e).__name__}", file=sys.stderr, flush=True)


def utc_midnight(now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def usage_snapshot(client_hash: str) -> tuple[float, int, int]:
    """(USD spent since midnight UTC, this client's requests in the last hour, all requests in the last minute)."""
    def q(cur):
        cur.execute("""
            select coalesce(sum(cost_usd) filter (where ts >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'), 0),
                   count(*) filter (where client_hash = %s and ts >= now() - interval '1 hour'),
                   count(*) filter (where ts >= now() - interval '1 minute')
            from hq_app.request_log
            where ts >= least(now() - interval '1 hour', date_trunc('day', now() at time zone 'utc') at time zone 'utc')""",
                    (client_hash,))
        spent, per_client, per_minute = cur.fetchone()
        return float(spent), int(per_client), int(per_minute)
    return db.run(_url(), q)


def spent_today() -> float:
    def q(cur):
        cur.execute("select coalesce(sum(cost_usd), 0) from hq_app.request_log "
                    "where ts >= date_trunc('day', now() at time zone 'utc') at time zone 'utc'")
        return float(cur.fetchone()[0])
    return db.run(_url(), q)


_STATS = """count(*), count(*) filter (where refused), count(*) filter (where error is not null),
  percentile_cont(0.5) within group (order by latency_ms), percentile_cont(0.9) within group (order by latency_ms),
  coalesce(sum(cost_usd), 0)"""


def _stats(row) -> dict:
    n, refused, errors, med, p90, cost = row
    return {"requests": int(n), "refusal_rate": round(refused / n, 3) if n else None, "errors": int(errors),
            "latency_ms_median": round(med) if med is not None else None,
            "latency_ms_p90": round(p90) if p90 is not None else None, "cost_usd": round(float(cost), 6)}


def status_windows() -> dict:
    """Aggregates for the last 24 hours and 7 days, overall and per release. Contains no question text."""
    def q(cur):
        out = {}
        for name, interval in (("last_24h", "24 hours"), ("last_7d", "7 days")):
            cur.execute(f"select {_STATS} from hq_app.request_log where ts >= now() - interval '{interval}'")
            overall = _stats(cur.fetchone())
            cur.execute(f"select release, {_STATS} from hq_app.request_log where ts >= now() - interval '{interval}' "
                        "group by release order by release")
            overall["by_release"] = {(r[0] or "unknown"): _stats(r[1:]) for r in cur.fetchall()}
            out[name] = overall
        return out
    return db.run(_url(), q)
