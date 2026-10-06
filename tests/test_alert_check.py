"""ops/alert_check.py, offline: fake store, fake SMTP, no network."""
import datetime
import io
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops import alert_check as ac  # noqa: E402

NOW = datetime.datetime(2026, 10, 7, 15, 30)
CFG = ac.Config(budget=0.50)
SMTP_ENV = {"ALERT_SMTP_USER": "u@example.test", "ALERT_SMTP_PASSWORD": "pw-secret", "ALERT_TO": "to@example.test"}


def snap(spent=0.0, requests=0, errors=0, release="abc1234", now=NOW):
    return ac.Snapshot(now, spent, requests, errors, release)


def keys(s, cfg=CFG):
    return [a.key for a in ac.evaluate(s, cfg)]


class FakeStore:
    def __init__(self, s=None, fail=None):
        self.s, self.fail, self.rows, self.inserts = s or snap(), fail, set(), 0

    def snapshot(self, cfg):
        if self.fail:
            raise self.fail
        return self.s

    def try_insert(self, key, period, detail):
        self.inserts += 1
        if (key, period) in self.rows:
            return False
        self.rows.add((key, period))
        return True


class FakeSMTP:
    sent, fail = [], False

    def __init__(self, host, port, timeout=None):
        if FakeSMTP.fail:
            raise OSError("connection refused")
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        self.tls = True

    def login(self, u, p):
        self.creds = (u, p)

    def send_message(self, m):
        FakeSMTP.sent.append(m)


@pytest.fixture(autouse=True)
def reset_smtp():
    FakeSMTP.sent, FakeSMTP.fail = [], False


def go(store, env=None, **kw):
    out = io.StringIO()
    code = ac.run(store, CFG, SMTP_ENV if env is None else env, smtp_factory=FakeSMTP, out=out,
                  now_fn=lambda: NOW, **kw)
    return code, out.getvalue()


# ---- budget rules: just under / at / over ----
@pytest.mark.parametrize("spent,expect", [
    (0.399999, []), (0.40, ["budget_80"]), (0.41, ["budget_80"]),
    (0.499999, ["budget_80"]), (0.50, ["budget_80", "budget_100"]), (0.75, ["budget_80", "budget_100"]),
])
def test_budget_edges(spent, expect):
    assert keys(snap(spent=spent)) == expect


def test_budget_follows_configured_budget():
    assert keys(snap(spent=0.50), ac.Config(budget=1.00)) == []
    assert keys(snap(spent=0.80), ac.Config(budget=1.00)) == ["budget_80"]


def test_budget_periods_are_utc_days():
    a = ac.evaluate(snap(spent=0.5), CFG)
    assert {x.period for x in a} == {"2026-10-07"}


# ---- error rule: both conditions ----
@pytest.mark.parametrize("requests,errors,fires", [
    (0, 0, False),        # zero requests
    (10, 2, False),       # rate 20%, count too low
    (10, 3, True),        # count 3 and rate 30%
    (12, 3, True),        # exactly 25%
    (13, 3, False),       # count ok, rate 23% too low
    (100, 3, False),      # count ok, rate 3%
    (4, 2, False),        # rate 50%, count too low
    (3, 3, True),
])
def test_error_edges(requests, errors, fires):
    assert (keys(snap(requests=requests, errors=errors)) == ["error_spike"]) is fires


def test_error_period_is_six_hour_block():
    p = lambda h: ac.block_period(NOW.replace(hour=h))
    assert p(0) == p(5) == "2026-10-07T00" and p(6) == "2026-10-07T06" and p(15) == p(12) == "2026-10-07T12"
    assert p(23) == "2026-10-07T18"


# ---- once per period, exit codes ----
def test_nothing_true_exits_0_and_writes_nothing():
    st = FakeStore(snap(spent=0.1, requests=5, errors=1))
    code, out = go(st)
    assert code == 0 and st.inserts == 0 and FakeSMTP.sent == [] and "rules true: none" in out


def test_new_alert_exits_1_then_suppressed_in_same_period_then_new_period_fires():
    st = FakeStore(snap(spent=0.5))
    code, _ = go(st)
    assert code == 1 and len(FakeSMTP.sent) == 1          # both recorded; only budget_100 is sent
    code, _ = go(st)
    assert code == 0 and len(FakeSMTP.sent) == 1          # same day: nothing new
    st.s = snap(spent=0.5, now=NOW + datetime.timedelta(days=1))
    tomorrow = NOW + datetime.timedelta(days=1)
    code = ac.run(st, CFG, SMTP_ENV, smtp_factory=FakeSMTP, out=io.StringIO(), now_fn=lambda: tomorrow)
    assert code == 1 and len(FakeSMTP.sent) == 2


def test_error_spike_repeats_only_in_a_new_block():
    st = FakeStore(snap(requests=10, errors=5))
    assert go(st)[0] == 1 and go(st)[0] == 0
    st.s = snap(requests=10, errors=5, now=NOW.replace(hour=22))
    assert go(st)[0] == 1


def test_test_alert_goes_through_full_path_with_minute_period():
    st = FakeStore()
    code, _ = go(st, test=True)
    assert code == 1 and st.rows == {("test", "2026-10-07T15:30")} and len(FakeSMTP.sent) == 1
    assert go(st, test=True)[0] == 0  # same minute: suppressed


# ---- email ----
def test_email_is_plain_and_has_expected_content():
    go(FakeStore(snap(spent=0.5)))
    m = [x for x in FakeSMTP.sent if x["Subject"].startswith("[hq-ask] daily budget reached")][0]
    assert m["Subject"] == "[hq-ask] daily budget reached ($0.50 of $0.50)"
    assert m["To"] == "to@example.test" and m["From"] == "u@example.test"
    body = m.get_content()
    for needle in ("$0.50 of $0.50", "2026-10-07", "abc1234", "00:00 UTC", "HQ_DAILY_BUDGET_USD"):
        assert needle in body
    assert m.get_content_type() == "text/plain"


def test_email_uses_smtp_host_and_starttls(monkeypatch):
    seen = {}

    class Rec(FakeSMTP):
        def starttls(self):
            seen["tls"] = True

        def __init__(self, host, port, timeout=None):
            seen["addr"] = (host, port)
            super().__init__(host, port, timeout)

    ac.send_email(ac.make_test_alert(CFG, NOW), SMTP_ENV, Rec)
    assert seen == {"addr": ("smtp.gmail.com", 587), "tls": True}
    ac.send_email(ac.make_test_alert(CFG, NOW), {**SMTP_ENV, "ALERT_SMTP_HOST": "h", "ALERT_SMTP_PORT": "2525"}, Rec)
    assert seen["addr"] == ("h", 2525)


def test_no_forbidden_content_in_any_message():
    st = FakeStore(snap(spent=0.5, requests=10, errors=5))
    go(st, env={**SMTP_ENV})
    texts = [m["Subject"] + m.get_content() for m in FakeSMTP.sent]
    texts.append(ac.check_failed_alert(RuntimeError("postgresql://hq_logger:pw@host/db"), CFG, NOW).body)
    for t in texts:
        assert "pw-secret" not in t and "postgresql://" not in t and "hq_logger:" not in t
        assert not re.search(r"\b[0-9a-f]{64}\b", t)          # no client hash
        assert "question" not in t.lower().replace("no question", "")


def test_status_url_included_when_set():
    cfg = ac.Config(status_url="https://example.test/status")
    assert "https://example.test/status" in ac.evaluate(snap(spent=0.5), cfg)[0].body


def test_missing_smtp_settings_skips_email_but_still_reports(tmp_path):
    summ = tmp_path / "s.md"
    code, out = go(FakeStore(snap(spent=0.5)), env={"ALERT_SMTP_USER": "u"}, summary_path=str(summ))
    assert code == 1 and FakeSMTP.sent == []
    assert "skipped" in out and "budget_100" in out and "budget_100" in summ.read_text(encoding="utf-8")


def test_smtp_failure_still_reports_and_exits_1():
    FakeSMTP.fail = True
    code, out = go(FakeStore(snap(spent=0.5)))
    assert code == 1 and "FAILED (OSError)" in out and "budget_100" in out
    assert "connection refused" not in out


def test_summary_file_gets_same_text_as_stdout(tmp_path):
    summ = tmp_path / "s.md"
    _, out = go(FakeStore(snap(spent=0.5)), summary_path=str(summ))
    assert "Subject: [hq-ask] daily budget reached" in summ.read_text(encoding="utf-8")


# ---- dry run ----
def test_dry_run_writes_nothing_sends_nothing_exits_0():
    st = FakeStore(snap(spent=0.5, requests=10, errors=5))
    code, out = go(st, dry_run=True)
    assert code == 0 and st.inserts == 0 and st.rows == set() and FakeSMTP.sent == []
    assert "would consider budget_100" in out and "would consider error_spike" in out


# ---- database unreachable ----
def test_database_unreachable_is_check_failed_exit_1_every_run():
    st = FakeStore(fail=ConnectionError("postgresql://hq_logger:secret@host"))
    for _ in range(2):  # no state to dedupe against: it reports every run
        code, out = go(st)
        assert code == 1
    assert len(FakeSMTP.sent) == 2 and FakeSMTP.sent[0]["Subject"] == "[hq-ask] alert check could not run (ConnectionError)"
    assert "secret" not in out and st.inserts == 0


def test_alert_log_insert_failure_still_reports():
    class Bad(FakeStore):
        def try_insert(self, *a):
            raise RuntimeError("table missing")
    code, out = go(Bad(snap(spent=0.5)))
    assert code == 1 and len(FakeSMTP.sent) == 1 and "insert failed" in out


def test_main_without_hq_log_url_is_check_failed(monkeypatch):
    monkeypatch.delenv("HQ_LOG_URL", raising=False)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    for k in SMTP_ENV:
        monkeypatch.delenv(k, raising=False)
    assert ac.main([]) == 1


# ---- config ----
def test_config_defaults_and_overrides():
    c = ac.Config.from_env({})
    assert (c.budget, c.warn_fraction, c.err_min_count, c.err_min_rate, c.err_window_min) == (0.50, 0.8, 3, 0.25, 60)
    c = ac.Config.from_env({"HQ_DAILY_BUDGET_USD": "2", "ALERT_BUDGET_WARN_FRACTION": "0.5", "ALERT_ERROR_MIN_COUNT": "5",
                            "ALERT_ERROR_MIN_RATE": "0.5", "ALERT_ERROR_WINDOW_MIN": "30", "ALERT_STATUS_URL": " u "})
    assert (c.budget, c.warn_fraction, c.err_min_count, c.err_min_rate, c.err_window_min, c.status_url) == (2, 0.5, 5, 0.5, 30, "u")


# ---- agreement with the service's own budget query ----
def test_spend_query_matches_service_day_boundary_and_column():
    import inspect
    from service import logging_store
    src = inspect.getsource(logging_store.spent_today)
    boundary = "date_trunc('day', now() at time zone 'utc') at time zone 'utc'"
    assert boundary in src and boundary in ac.SPENT_TODAY_SQL
    assert "sum(cost_usd)" in src and "sum(cost_usd)" in ac.SPENT_TODAY_SQL
    assert "hq_app.request_log" in src and "hq_app.request_log" in ac.SPENT_TODAY_SQL
    assert boundary in ac.SNAPSHOT_SQL


def test_jump_past_both_budget_thresholds_sends_only_reached():
    store = FakeStore(snap(spent=0.55))
    code, out = go(store)
    assert code == 1
    assert [m["Subject"] for m in FakeSMTP.sent] == ["[hq-ask] daily budget reached ($0.55 of $0.50)"]
    assert {k for k, _ in store.rows} == {"budget_80", "budget_100"}  # the warning is recorded, so it cannot fire later
    code, _ = go(store)
    assert code == 0 and len(FakeSMTP.sent) == 1
