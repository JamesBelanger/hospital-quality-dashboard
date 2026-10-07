"""Request limits, enforced from the request log so they hold across restarts and scale-to-zero.

Checked before any model call. Limits, all from environment variables:
  HQ_DAILY_BUDGET_USD   total model spend since midnight UTC (default 0.50)      -> 429 when reached
  HQ_CLIENT_PER_HOUR    requests per client in the last hour (default 20)          -> 429 when exceeded
  HQ_GLOBAL_PER_MINUTE  requests from everyone in the last minute (default 30)     -> 429 when exceeded
  HQ_MAX_INFLIGHT       requests being answered at the same moment (default 6)     -> 429 "busy", Retry-After 5
  HQ_INFLIGHT_COST_USD  spend assumed for each request still running (default 0.01), added to today's spend

A request is written to the log only when it FINISHES, so a burst that arrives together would all be counted as
zero. To close that gap the process keeps a registry of requests in flight (client hash + start time). Every limit
counts the logged rows PLUS the requests in flight, and check-and-register is atomic. This is valid because the
service runs as one process; the database stays the source of truth across restarts.

If the log cannot be read the budget cannot be checked, so the request is refused with 503
(fail closed): an endpoint that spends money must not run unmetered.

Only requests that reach ask() are logged, so a refused (429/503) request does not count against a limit.
"""
from __future__ import annotations

import datetime
import hashlib
import os
import threading
import time
from dataclasses import dataclass

# Fixed fallback so local runs work. Production sets its own secret HQ_HASH_SALT, so a leaked log cannot be
# reversed by hashing the IPv4 space with a known salt.
_DEFAULT_SALT = "hq-ask-demo-salt-not-secret"


class LimitExceeded(Exception):
    def __init__(self, status: int, detail: str, retry_after_s: int | None = None):
        super().__init__(detail)
        self.status, self.detail, self.retry_after_s = status, detail, retry_after_s


@dataclass
class Settings:
    daily_budget_usd: float
    client_per_hour: int
    global_per_minute: int
    inflight_cost_usd: float = 0.01
    max_inflight: int = 6


def settings() -> Settings:
    e = os.environ
    return Settings(float(e.get("HQ_DAILY_BUDGET_USD", "0.50")), int(e.get("HQ_CLIENT_PER_HOUR", "20")),
                    int(e.get("HQ_GLOBAL_PER_MINUTE", "30")), float(e.get("HQ_INFLIGHT_COST_USD", "0.01")),
                    int(e.get("HQ_MAX_INFLIGHT", "6")))


def client_hash(forwarded_for: str | None, peer: str | None) -> str:
    """SHA-256 of (client address + salt). The raw IP is never stored.

    The address is the LAST X-Forwarded-For hop: the service sits behind exactly one proxy (the Container Apps
    ingress), which appends the address it saw. Earlier hops are whatever the caller typed, so trusting the
    first one would let anyone dodge the per-client limit by inventing a new value per request.
    """
    ip = (forwarded_for or "").split(",")[-1].strip() or peer or "unknown"
    salt = os.environ.get("HQ_HASH_SALT", _DEFAULT_SALT)
    return hashlib.sha256((ip + salt).encode("utf-8")).hexdigest()


def next_reset(now: datetime.datetime | None = None) -> datetime.datetime:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)


# ---- requests in flight (this process only) ----
_inflight_lock = threading.Lock()
_inflight: dict[int, tuple[str, float]] = {}  # token -> (client hash, start time)
_next_token = 0
INFLIGHT_MAX_AGE_S = 300  # an entry this old is a leak (a request cannot run this long); it is dropped, not counted


def inflight_count() -> int:
    with _inflight_lock:
        return len(_inflight)


def release(token: int | None) -> None:
    """Remove a request from the in-flight registry (safe to call twice)."""
    if token is not None:
        with _inflight_lock:
            _inflight.pop(token, None)


def admit(client: str, usage_fn=None, now: datetime.datetime | None = None) -> int:
    """Atomically count the requests already in flight, register this one, then run the limit checks against
    logged rows + in-flight requests. Returns a token the caller MUST pass to `release` (in a `finally`).
    Raises LimitExceeded (and registers nothing) if the request must not run.

    Order matters: in-flight is counted BEFORE the log is read. A request writes its log row and only then
    leaves the registry, so it is always seen by at least one of the two reads (never missed; at worst seen
    twice, which errs on the side of refusing)."""
    global _next_token
    s = settings()
    with _inflight_lock:
        cutoff = time.monotonic() - INFLIGHT_MAX_AGE_S
        for k in [k for k, (_, t0) in _inflight.items() if t0 < cutoff]:
            del _inflight[k]
        if len(_inflight) >= s.max_inflight:
            raise LimitExceeded(429, "The demo is busy answering other questions. Try again in a few seconds.", 5)
        mine = sum(1 for c, _ in _inflight.values() if c == client)
        others = len(_inflight)
        _next_token += 1
        token = _next_token
        _inflight[token] = (client, time.monotonic())
    try:
        check(client, usage_fn, now, inflight=(mine, others))
    except BaseException:
        release(token)
        raise
    return token


def check(client: str, usage_fn=None, now: datetime.datetime | None = None, inflight: tuple[int, int] = (0, 0)) -> None:
    """Raise LimitExceeded if this request must not run. `usage_fn(client)` returns
    (usd spent today, this client's requests in the last hour, all requests in the last minute).
    `inflight` = (this client's other requests in flight, all other requests in flight); they are counted as
    logged requests, and each adds `inflight_cost_usd` to today's spend."""
    if usage_fn is None:
        from service.logging_store import usage_snapshot as usage_fn
    s = settings()
    now = now or datetime.datetime.now(datetime.timezone.utc)
    try:
        spent, per_client, per_minute = usage_fn(client)
    except Exception as e:  # noqa: BLE001  (fail closed)
        raise LimitExceeded(503, "The demo cannot check its usage limits right now, so it is not answering. "
                                 "Please try again later.", 60) from e
    reset = next_reset(now)
    mine, others = inflight
    spent += others * s.inflight_cost_usd
    per_client += mine
    per_minute += others
    if spent >= s.daily_budget_usd:
        raise LimitExceeded(429, "This demo's daily budget is used up. It resets at "
                                 f"{reset:%H:%M} UTC ({reset:%Y-%m-%d}).", int((reset - now).total_seconds()))
    if per_minute >= s.global_per_minute:
        raise LimitExceeded(429, "The demo is busy (too many requests in the last minute). Try again shortly.", 60)
    if per_client >= s.client_per_hour:
        raise LimitExceeded(429, f"You have reached the limit of {s.client_per_hour} questions per hour. "
                                 "Try again later.", 3600)
