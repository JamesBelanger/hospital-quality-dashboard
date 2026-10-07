"""Run model-written SQL: guard first, then execute as the read-only `hq_reader` login."""
from __future__ import annotations

import datetime
import decimal
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from service import db, sql_guard

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

# Client-side deadline for model-written SQL, counted from the start of execute() to the end of the fetch.
# The role's own statement_timeout (5 s) is the first stop; this covers a stall the server timeout cannot see
# (slow fetch, a hung network path).
QUERY_DEADLINE_S = 8.0
TIMEOUT_MESSAGE = "canceling statement due to timeout (the query took longer than the time allowed)"


class GuardRejected(Exception):
    """The query failed sql_guard.check; the message is safe to show."""


class DatabaseError(Exception):
    """The query was allowed but the database could not run it (bad column, timeout, ...)."""


class _DeadlineExceeded(Exception):
    pass


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
            conn = cur.connection
            fired = threading.Event()

            def _cancel():
                fired.set()
                try:
                    conn.cancel()
                except Exception:  # noqa: BLE001  (best effort; the connection is discarded below either way)
                    pass

            timer = threading.Timer(QUERY_DEADLINE_S, _cancel)
            timer.daemon = True
            timer.start()
            try:
                cur.execute(safe)
                columns = [d.name for d in cur.description]
                fetched = cur.fetchmany(sql_guard.MAX_ROWS + 1)  # the guard already added a LIMIT; this is a second fence
            except psycopg.Error as e:
                if fired.is_set():
                    db.discard(conn)
                    raise _DeadlineExceeded() from e
                raise
            finally:
                timer.cancel()
            if fired.is_set():
                db.discard(conn)
                raise _DeadlineExceeded()
            return columns, [[_json_safe(v) for v in r] for r in fetched[:sql_guard.MAX_ROWS]]

        columns, rows = db.run(os.environ["HQ_READER_URL"], _exec)
    except _DeadlineExceeded as e:
        raise DatabaseError(TIMEOUT_MESSAGE) from e
    except psycopg.Error as e:
        raise DatabaseError(str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__) from e
    return SqlResult(safe, columns, rows, len(rows), int((time.perf_counter() - t0) * 1000))
