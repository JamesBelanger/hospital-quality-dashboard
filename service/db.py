"""One long-lived database connection per role URL.

Opening a connection through the pooler takes seconds, so the service keeps one open per URL and
reuses it. Access to a connection is serialised by a lock of its own (psycopg connections are not for
concurrent use), so a slow query on the hospital-data login does not hold up documentation search or the
request log, which use other URLs. A caller waits at most LOCK_TIMEOUT_S for the lock and then gets an
`OperationalError` ("busy"), which every caller already treats as a database failure. Queries here take
milliseconds once the connection is warm. If the connection has been dropped (pooler idle timeout,
network blip) the statement is retried once on a fresh connection; a second failure propagates. A statement
cancelled by the role's statement_timeout is NOT retried: repeating it would only double the wait.
"""
from __future__ import annotations

import threading
from typing import Callable, TypeVar

import psycopg

T = TypeVar("T")
CONNECT_TIMEOUT_S = 20
LOCK_TIMEOUT_S = 8

_registry = threading.Lock()  # guards the two dicts below, never held across database work
_locks: dict[str, threading.Lock] = {}
_conns: dict[str, "psycopg.Connection"] = {}


def _connect(url: str):
    return psycopg.connect(url, autocommit=True, connect_timeout=CONNECT_TIMEOUT_S)


def _lock_for(url: str) -> threading.Lock:
    with _registry:
        return _locks.setdefault(url, threading.Lock())


def _drop(url: str) -> None:
    conn = _conns.pop(url, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def discard(conn) -> None:
    """Close `conn` and forget it, whichever URL it belongs to (used after a cancelled or abandoned query)."""
    with _registry:
        for url, c in list(_conns.items()):
            if c is conn:
                del _conns[url]
    try:
        conn.close()
    except Exception:
        pass


def run(url: str, fn: Callable[[object], T], lock_timeout: float = LOCK_TIMEOUT_S) -> T:
    """Call `fn(cursor)` on the shared connection for `url` and return its result.

    `fn` must do all its fetching inside the call (the cursor is only valid while the lock is held)."""
    lock = _lock_for(url)
    if not lock.acquire(timeout=lock_timeout):
        raise psycopg.OperationalError(f"the database connection is busy (waited {lock_timeout:g} s)")
    try:
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
    finally:
        lock.release()


def close_all() -> None:
    with _registry:
        urls = list(_conns)
    for url in urls:
        lock = _lock_for(url)
        if lock.acquire(timeout=LOCK_TIMEOUT_S):
            try:
                _drop(url)
            finally:
                lock.release()
