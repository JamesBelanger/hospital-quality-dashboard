"""Scheduled alert check for the "Ask the data" service. Runs outside the service (GitHub Actions cron),
so it still works when the service is down or scaled to zero.

Reads `hq_app.request_log` as the `hq_logger` login (HQ_LOG_URL) and evaluates:
  budget_80     today's (UTC) spend >= ALERT_BUDGET_WARN_FRACTION of HQ_DAILY_BUDGET_USD   once per UTC day
  budget_100    today's spend >= the daily budget (the service is now refusing)            once per UTC day
  error_spike   in the last ALERT_ERROR_WINDOW_MIN minutes: failures >= ALERT_ERROR_MIN_COUNT
                and >= ALERT_ERROR_MIN_RATE of requests                                   once per 6-hour UTC block
  check_failed  this check could not reach the database / the query failed                 every run
A rule that is true tries to insert (alert_key, period) into `hq_app.alert_log`; only a row actually inserted
is a NEW alert (that is how repeats are suppressed). Each new alert is emailed (if SMTP settings exist), written to
the GitHub job summary and stdout. Exit code 1 if any new alert fired, else 0.

  python -m ops.alert_check            normal run
  python -m ops.alert_check --dry-run  evaluate and print; write nothing, send nothing
  python -m ops.alert_check --test     fire a synthetic `test` alert (period = current UTC minute) through the full path

Emails and summaries contain only counts, dollar amounts, the release id and fixed text: never question text,
client hashes or connection strings.
"""
from __future__ import annotations

import argparse
import datetime
import os
import smtplib
import sys
from dataclasses import dataclass, field
from email.message import EmailMessage

# Same day boundary and column as service/logging_store.spent_today (tests/test_alert_check.py checks they agree).
DAY_START = "date_trunc('day', now() at time zone 'utc') at time zone 'utc'"
SPENT_TODAY_SQL = ("select coalesce(sum(cost_usd), 0) from hq_app.request_log "
                   f"where ts >= {DAY_START}")
SNAPSHOT_SQL = f"""
select (now() at time zone 'utc'),
       ({SPENT_TODAY_SQL}),
       (select count(*) from hq_app.request_log where ts >= now() - make_interval(mins => %(win)s)),
       (select count(*) from hq_app.request_log where ts >= now() - make_interval(mins => %(win)s) and error is not null),
       (select release from hq_app.request_log order by ts desc limit 1)"""
INSERT_SQL = ("insert into hq_app.alert_log (alert_key, period, detail) values (%s, %s, %s) "
              "on conflict do nothing returning alert_key")

TODO = {
    "budget_80": "Nothing is wrong yet. The spend cap stops spending at 100%. To raise it: az containerapp update "
                 "-n hq-ask -g rg-hq-ask --set-env-vars HQ_DAILY_BUDGET_USD=<usd> (infra/DEPLOY.md, 'Change the limits').",
    "budget_100": "The service now answers 429 until 00:00 UTC, when the day's budget resets. To raise the cap now: "
                  "az containerapp update -n hq-ask -g rg-hq-ask --set-env-vars HQ_DAILY_BUDGET_USD=<usd> "
                  "(infra/DEPLOY.md, 'Change the limits').",
    "error_spike": "Look at recent failures: select ts, release, error from hq_app.request_log where error is not null "
                   "order by ts desc limit 50 (Supabase SQL editor), and az containerapp logs show -n hq-ask -g rg-hq-ask "
                   "--follow. If a recent release caused it, roll back (infra/DEPLOY.md, 'Roll back').",
    "check_failed": "The alert check could not read the database, so no rule was evaluated. Check the Supabase project "
                    "(free tier pauses after idle), HQ_LOG_URL, and the failing run's log. The service itself fails closed "
                    "(503) if it cannot read the log.",
    "test": "This is a synthetic test alert. Delivery works.",
}


@dataclass
class Config:
    budget: float = 0.50
    warn_fraction: float = 0.8
    err_min_count: int = 3
    err_min_rate: float = 0.25
    err_window_min: int = 60
    status_url: str = ""

    @classmethod
    def from_env(cls, env=os.environ) -> "Config":
        def f(k, d, t):
            v = (env.get(k) or "").strip()
            return t(v) if v else d
        return cls(f("HQ_DAILY_BUDGET_USD", 0.50, float), f("ALERT_BUDGET_WARN_FRACTION", 0.8, float),
                   f("ALERT_ERROR_MIN_COUNT", 3, int), f("ALERT_ERROR_MIN_RATE", 0.25, float),
                   f("ALERT_ERROR_WINDOW_MIN", 60, int), (env.get("ALERT_STATUS_URL") or "").strip())


@dataclass
class Snapshot:
    now: datetime.datetime          # UTC, naive or aware, as the database reports it
    spent: float
    requests: int                   # in the error window
    errors: int                     # in the error window
    release: str | None = None


@dataclass
class Alert:
    key: str
    period: str
    subject: str
    body: str
    detail: dict = field(default_factory=dict)


# ---------- rules ----------
def _cents(x: float) -> float:
    return round(float(x), 6)


def _fmt(x: float) -> str:
    return f"${x:.2f}"


def day_period(now) -> str:
    return f"{now:%Y-%m-%d}"


def block_period(now) -> str:
    return f"{now:%Y-%m-%d}T{(now.hour // 6) * 6:02d}"


def _body(key: str, headline: str, facts: list[str], snap: Snapshot | None, cfg: Config, when) -> str:
    lines = [headline, ""] + facts
    lines.append(f"Time (UTC): {when:%Y-%m-%d %H:%M}")
    if snap is not None:
        lines.append(f"Release: {snap.release or 'unknown'}")
    if cfg.status_url:
        lines.append(f"Status: {cfg.status_url}")
    lines += ["", "What to do: " + TODO[key]]
    return "\n".join(lines)


def evaluate(snap: Snapshot, cfg: Config) -> list[Alert]:
    """Pure: every rule that is true for this snapshot (whether or not it was already alerted)."""
    out: list[Alert] = []
    spent, budget = _cents(snap.spent), _cents(cfg.budget)
    pct = round(100 * spent / budget) if budget else 0
    spend_facts = [f"Spend today (UTC day {day_period(snap.now)}): {_fmt(spent)} of {_fmt(budget)} ({pct}%)"]
    detail = {"spent_usd": spent, "budget_usd": budget}
    if spent >= _cents(cfg.warn_fraction * budget):
        out.append(Alert("budget_80", day_period(snap.now),
                         f"[hq-ask] daily budget {pct}% used ({_fmt(spent)} of {_fmt(budget)})",
                         _body("budget_80", f"Today's spend passed {round(cfg.warn_fraction * 100)}% of the daily budget.",
                               spend_facts, snap, cfg, snap.now), detail))
    if spent >= budget:
        out.append(Alert("budget_100", day_period(snap.now),
                         f"[hq-ask] daily budget reached ({_fmt(spent)} of {_fmt(budget)})",
                         _body("budget_100", "The daily budget is used up; the service is refusing requests.",
                               spend_facts, snap, cfg, snap.now), detail))
    if snap.errors >= cfg.err_min_count and snap.requests and snap.errors / snap.requests >= cfg.err_min_rate:
        w = cfg.err_window_min
        out.append(Alert("error_spike", block_period(snap.now),
                         f"[hq-ask] error spike ({snap.errors} of {snap.requests} requests failed in the last {w} min)",
                         _body("error_spike", "Requests are failing.",
                               [f"Failed requests in the last {w} minutes: {snap.errors} of {snap.requests} "
                                f"({round(100 * snap.errors / snap.requests)}%)",
                                f"Thresholds: at least {cfg.err_min_count} failures and {round(cfg.err_min_rate * 100)}%"],
                               snap, cfg, snap.now),
                         {"errors": snap.errors, "requests": snap.requests, "window_min": w}))
    return out


def check_failed_alert(exc: BaseException, cfg: Config, now: datetime.datetime) -> Alert:
    name = type(exc).__name__  # the class only: driver messages can contain host names
    return Alert("check_failed", f"{now:%Y-%m-%dT%H:%M:%S}", f"[hq-ask] alert check could not run ({name})",
                 _body("check_failed", "The alert check could not evaluate its rules.",
                       [f"Error type: {name}"], None, cfg, now), {"error_type": name})


def make_test_alert(cfg: Config, now: datetime.datetime, release: str | None = None) -> Alert:
    snap = Snapshot(now, 0.0, 0, 0, release)
    return Alert("test", f"{now:%Y-%m-%dT%H:%M}", "[hq-ask] test alert",
                 _body("test", "Test alert from ops/alert_check.py.", [], snap, cfg, now), {"test": True})


# ---------- database ----------
class Store:
    """hq_logger connection. Autocommit, so each insert is durable and visible immediately."""

    def __init__(self, url: str):
        import psycopg
        self.conn = psycopg.connect(url, autocommit=True, connect_timeout=20)

    def snapshot(self, cfg: Config) -> Snapshot:
        cur = self.conn.cursor()
        cur.execute(SNAPSHOT_SQL, {"win": cfg.err_window_min})
        now, spent, n, errs, release = cur.fetchone()
        return Snapshot(now, float(spent), int(n), int(errs), release)

    def try_insert(self, key: str, period: str, detail: dict) -> bool:
        """True only if this (key, period) row was newly inserted."""
        from psycopg.types.json import Jsonb
        cur = self.conn.cursor()
        cur.execute(INSERT_SQL, (key, period, Jsonb(detail)))
        return cur.fetchone() is not None

    def close(self):
        self.conn.close()


# ---------- delivery ----------
def send_email(alert: Alert, env, smtp_factory=smtplib.SMTP) -> str:
    """Returns 'sent' or 'skipped (SMTP settings not set)'. Raises on SMTP failure."""
    user, pw, to = (env.get(k) or "" for k in ("ALERT_SMTP_USER", "ALERT_SMTP_PASSWORD", "ALERT_TO"))
    if not (user and pw and to):
        return "skipped (ALERT_SMTP_USER / ALERT_SMTP_PASSWORD / ALERT_TO not all set)"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = alert.subject, user, to
    msg.set_content(alert.body)
    host, port = env.get("ALERT_SMTP_HOST") or "smtp.gmail.com", int(env.get("ALERT_SMTP_PORT") or 587)
    with smtp_factory(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    return "sent"


def _emit(text: str, summary_path: str | None, out) -> None:
    print(text, file=out, flush=True)
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(text + "\n")
        except OSError as e:
            print(f"could not write job summary: {type(e).__name__}", file=out, flush=True)


def _deliver(alert: Alert, env, smtp_factory, summary_path, out) -> None:
    try:
        mail = send_email(alert, env, smtp_factory)
    except Exception as e:  # noqa: BLE001  (an SMTP failure must not hide the alert)
        mail = f"FAILED ({type(e).__name__})"
    _emit(f"## ALERT {alert.key} ({alert.period})\n\nSubject: {alert.subject}\n\n{alert.body}\n\nEmail: {mail}\n",
          summary_path, out)


# ---------- run ----------
def run(store, cfg: Config, env, *, dry_run=False, test=False, smtp_factory=smtplib.SMTP,
        summary_path: str | None = None, out=sys.stdout, now_fn=None) -> int:
    """`store` is a Store (or anything with snapshot/try_insert). Returns the exit code."""
    now_fn = now_fn or (lambda: datetime.datetime.now(datetime.timezone.utc))
    try:
        if test:
            snap = store.snapshot(cfg)
            candidates = [make_test_alert(cfg, now_fn(), snap.release)]
        else:
            snap = store.snapshot(cfg)
            candidates = evaluate(snap, cfg)
    except Exception as e:  # noqa: BLE001
        alert = check_failed_alert(e, cfg, now_fn())
        if dry_run:
            _emit(f"DRY RUN: check failed ({type(e).__name__})", summary_path, out)
            return 1
        _deliver(alert, env, smtp_factory, summary_path, out)  # no state to dedupe against: every run
        return 1
    if not test:
        _emit(f"Checked {snap.now:%Y-%m-%d %H:%M} UTC: spend {_fmt(snap.spent)} of {_fmt(cfg.budget)}; last "
              f"{cfg.err_window_min} min {snap.requests} requests, {snap.errors} failed; "
              f"rules true: {', '.join(a.key for a in candidates) or 'none'}", summary_path, out)
    if dry_run:
        for a in candidates:
            _emit(f"DRY RUN would consider {a.key} ({a.period}): {a.subject}", summary_path, out)
        return 0
    new = []
    for a in candidates:
        try:
            fresh = store.try_insert(a.key, a.period, a.detail)
        except Exception as e:  # noqa: BLE001  (cannot record it, so cannot dedupe: report it rather than drop it)
            _emit(f"alert_log insert failed for {a.key} ({type(e).__name__}); reporting anyway", summary_path, out)
            fresh = True
        if fresh:
            new.append(a)
    # Spend can jump past both thresholds between two checks: the warning is recorded but only "reached" is sent.
    if any(a.key == "budget_100" for a in new):
        send = [a for a in new if a.key != "budget_80"]
    else:
        send = new
    for a in send:
        _deliver(a, env, smtp_factory, summary_path, out)
    return 1 if new else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="evaluate and print; insert and send nothing")
    ap.add_argument("--test", action="store_true", help="fire a synthetic test alert through the full path")
    a = ap.parse_args(argv)
    cfg, env = Config.from_env(), os.environ
    summary = env.get("GITHUB_STEP_SUMMARY")
    try:
        store = Store(env["HQ_LOG_URL"])
    except Exception as e:  # noqa: BLE001  (missing variable or unreachable database)
        class _Down:
            def snapshot(self, cfg):
                raise e
        return run(_Down(), cfg, env, dry_run=a.dry_run, test=a.test, summary_path=summary)
    try:
        return run(store, cfg, env, dry_run=a.dry_run, test=a.test, summary_path=summary)
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
