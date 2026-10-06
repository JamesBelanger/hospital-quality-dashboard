"""Run model-written SQL: guard first, then execute as the read-only `hq_reader` login."""
from __future__ import annotations

import datetime
import decimal
import os
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from service import db, sql_guard

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class GuardRejected(Exception):
    """The query failed sql_guard.check; the message is safe to show."""


class DatabaseError(Exception):
    """The query was allowed but the database could not run it (bad column, timeout, ...)."""


@dataclass
class SqlResult:
    sql_run: str  # the guarded query actually executed (row limit applied)
    columns: list[str]
    rows: list[list]
    row_count: int
    elapsed_ms: int


def _json_safe(v):
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() and v.as_tuple().exponent >= 0 else float(v)
    if isinstance(v, (datetime.date, datetime.datetime)):
        return v.isoformat()
    return v


def run_sql(sql: str) -> SqlResult:
    try:
        safe = sql_guard.check(sql)
    except sql_guard.UnsafeSQL as e:
        raise GuardRejected(str(e)) from e
    t0 = time.perf_counter()
    try:
        def _exec(cur):
            cur.execute(safe)
            return [d.name for d in cur.description], [[_json_safe(v) for v in r] for r in cur.fetchall()]

        columns, rows = db.run(os.environ["HQ_READER_URL"], _exec)
    except psycopg.Error as e:
        raise DatabaseError(str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__) from e
    return SqlResult(safe, columns, rows, len(rows), int((time.perf_counter() - t0) * 1000))
