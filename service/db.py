"""One long-lived database connection per role URL.

Opening a connection through the pooler takes seconds, so the service keeps one open per URL and
reuses it. Access is serialised by a lock (psycopg connections are not for concurrent use); queries
here take milliseconds once the connection is warm. If the connection has been dropped (pooler idle
timeout, network blip) the statement is retried once on a fresh connection; a second failure
propagates. A statement cancelled by the role's statement_timeout is NOT retried: repeating it
would only double the wait.
"""
from __future__ import annotations

import threading
from typing import Callable, TypeVar

import psycopg

T = TypeVar("T")
CONNECT_TIMEOUT_S = 20

_lock = threading.Lock()
_conns: dict[str, "psycopg.Connection"] = {}


def _connect(url: str):
    return psycopg.connect(url, autocommit=True, connect_timeout=CONNECT_TIMEOUT_S)


def _drop(url: str) -> None:
    conn = _conns.pop(url, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def run(url: str, fn: Callable[[object], T]) -> T:
    """Call `fn(cursor)` on the shared connection for `url` and return its result.

    `fn` must do all its fetching inside the call (the cursor is only valid while the lock is held)."""
    with _lock:
        for attempt in (0, 1):
            try:
                conn = _conns.get(url)
                if conn is None or getattr(conn, "closed", False):
                    conn = _conns[url] = _connect(url)
                return fn(conn.cursor())
            except psycopg.errors.QueryCanceled:
                raise
            except psycopg.OperationalError:
                _drop(url)
                if attempt == 1:
                    raise
    raise AssertionError("unreachable")  # pragma: no cover


def close_all() -> None:
    with _lock:
        for url in list(_conns):
            _drop(url)
