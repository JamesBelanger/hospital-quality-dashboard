"""Request limits, enforced from the request log so they hold across restarts and scale-to-zero.

Checked before any model call. Three limits, all from environment variables:
  HQ_DAILY_BUDGET_USD   total model spend since midnight UTC (default 0.50)      -> 429 when reached
  HQ_CLIENT_PER_HOUR    requests per client in the last hour (default 20)          -> 429 when exceeded
  HQ_GLOBAL_PER_MINUTE  requests from everyone in the last minute (default 30)     -> 429 when exceeded

If the log cannot be read the budget cannot be checked, so the request is refused with 503
(fail closed): an endpoint that spends money must not run unmetered.

Only requests that reach ask() are logged, so a refused (429/503) request does not count against a limit.
"""
from __future__ import annotations

import datetime
import hashlib
import os
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


def settings() -> Settings:
    e = os.environ
    return Settings(float(e.get("HQ_DAILY_BUDGET_USD", "0.50")), int(e.get("HQ_CLIENT_PER_HOUR", "20")),
                    int(e.get("HQ_GLOBAL_PER_MINUTE", "30")))


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


def check(client: str, usage_fn=None, now: datetime.datetime | None = None) -> None:
    """Raise LimitExceeded if this request must not run. `usage_fn(client)` returns
    (usd spent today, this client's requests in the last hour, all requests in the last minute)."""
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
    if spent >= s.daily_budget_usd:
        raise LimitExceeded(429, "This demo's daily budget is used up. It resets at "
                                 f"{reset:%H:%M} UTC ({reset:%Y-%m-%d}).", int((reset - now).total_seconds()))
    if per_minute >= s.global_per_minute:
        raise LimitExceeded(429, "The demo is busy (too many requests in the last minute). Try again shortly.", 60)
    if per_client >= s.client_per_hour:
        raise LimitExceeded(429, f"You have reached the limit of {s.client_per_hour} questions per hour. "
                                 "Try again later.", 3600)
