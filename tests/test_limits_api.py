"""Limits, /status, /health and the /ask wiring, all offline (fake log store, fake ask())."""
import datetime
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import api, limits, logging_store, pipeline  # noqa: E402

NOW = datetime.datetime(2026, 10, 7, 15, 30, tzinfo=datetime.timezone.utc)


def usage(spent=0.0, per_client=0, per_minute=0):
    return lambda client: (spent, per_client, per_minute)


def status_of(usage_fn):
    try:
        limits.check("c", usage_fn, NOW)
    except limits.LimitExceeded as e:
        return e
    return None


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("HQ_DAILY_BUDGET_USD", "HQ_CLIENT_PER_HOUR", "HQ_GLOBAL_PER_MINUTE", "HQ_HASH_SALT",
              "HQ_PLAN_PROMPT", "HQ_ANSWER_PROMPT", "HQ_SCHEMA_PROMPT", "HQ_MODEL"):
        monkeypatch.delenv(k, raising=False)


def test_under_all_limits_passes():
    assert status_of(usage(0.49, 19, 29)) is None


def test_daily_budget_429_names_reset_time():
    e = status_of(usage(spent=0.50))
    assert e.status == 429 and "daily budget" in e.detail and "00:00 UTC (2026-10-08)" in e.detail
    assert e.retry_after_s == 8.5 * 3600


def test_budget_env_override(monkeypatch):
    monkeypatch.setenv("HQ_DAILY_BUDGET_USD", "0.000001")
    assert status_of(usage(spent=0.00001)).status == 429
    monkeypatch.setenv("HQ_DAILY_BUDGET_USD", "5")
    assert status_of(usage(spent=0.7)) is None


def test_per_client_limit():
    assert status_of(usage(per_client=19)) is None
    e = status_of(usage(per_client=20))
    assert e.status == 429 and "per hour" in e.detail


def test_global_per_minute_limit():
    assert status_of(usage(per_minute=29)) is None
    assert status_of(usage(per_minute=30)).status == 429


def test_log_unreachable_fails_closed_503():
    def boom(client):
        raise ConnectionError("log db down")
    e = status_of(boom)
    assert e.status == 503


def test_client_hash_uses_last_forwarded_hop_and_never_contains_ip():
    # The last hop is the one the ingress proxy appended; earlier hops are caller-supplied.
    h1 = limits.client_hash("10.0.0.1, 203.0.113.9", "10.0.0.2")
    assert h1 == limits.client_hash("203.0.113.9", "99.99.99.99")
    assert h1 == limits.client_hash("spoofed-value, another-fake, 203.0.113.9", None)  # forged hops change nothing
    assert h1 != limits.client_hash(None, "10.0.0.2")
    assert limits.client_hash(None, "10.0.0.2") == limits.client_hash("", "10.0.0.2")
    assert len(h1) == 64 and "203.0.113.9" not in h1


def test_salt_changes_hash(monkeypatch):
    a = limits.client_hash("1.2.3.4", None)
    monkeypatch.setenv("HQ_HASH_SALT", "other")
    assert limits.client_hash("1.2.3.4", None) != a


# ---- API wiring ----
class FakeAnswer:
    question = "q"

    def model_dump(self, mode="json"):
        return {"question": "q", "refused": False}


@pytest.fixture()
def client(monkeypatch):
    logged, asked = [], []
    monkeypatch.setattr(logging_store, "usage_snapshot", lambda c: (0.0, 0, 0))
    monkeypatch.setattr(logging_store, "log_request", lambda *a, **k: logged.append((a, k)))

    def fake_ask(q):
        asked.append(q)
        return FakeAnswer()
    monkeypatch.setattr(pipeline, "ask", fake_ask)
    c = TestClient(api.app)
    c.logged, c.asked, c.mp = logged, asked, monkeypatch
    return c


def test_health_has_release_model_prompts_and_no_db(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.headers["X-Release"] == api.RELEASE
    j = r.json()
    assert j["model"] == "gpt-6-luna" and j["prompt_versions"] == {
        "plan": pipeline.PLAN_PROMPT, "schema": pipeline.SCHEMA_PROMPT, "answer": pipeline.ANSWER_PROMPT}
    assert not client.logged and not client.asked


def test_ask_logs_and_sets_release_header(client):
    r = client.post("/ask", json={"question": "How many hospitals?"}, headers={"X-Forwarded-For": "1.2.3.4"})
    assert r.status_code == 200 and r.headers["X-Release"] == api.RELEASE
    assert client.asked == ["How many hospitals?"] and len(client.logged) == 1
    args, _ = client.logged[0]
    assert isinstance(args[0], FakeAnswer) and len(args[1]) == 64 and "1.2.3.4" not in args[1]


def test_over_budget_returns_429_without_calling_ask_or_logging(client):
    client.mp.setattr(logging_store, "usage_snapshot", lambda c: (9.0, 0, 0))
    r = client.post("/ask", json={"question": "How many hospitals?"})
    assert r.status_code == 429 and "daily budget" in r.json()["detail"] and "Retry-After" in r.headers
    assert r.headers["X-Release"] == api.RELEASE
    assert not client.asked and not client.logged


def test_log_down_returns_503_without_calling_ask(client):
    def boom(c):
        raise ConnectionError("down")
    client.mp.setattr(logging_store, "usage_snapshot", boom)
    r = client.post("/ask", json={"question": "How many hospitals?"})
    assert r.status_code == 503 and not client.asked


def test_exception_in_ask_is_logged_with_error_and_returns_502(client):
    def bad(q):
        raise RuntimeError("secret connection string")
    client.mp.setattr(pipeline, "ask", bad)
    r = client.post("/ask", json={"question": "How many hospitals?"})
    assert r.status_code == 502 and "secret" not in r.text
    args, kw = client.logged[0]
    assert args[0] is None and kw["error"].startswith("RuntimeError") and kw["question"] == "How many hospitals?"


def test_status_has_windows_and_budget_but_no_question_text(client):
    window = {"requests": 3, "refusal_rate": 0.333, "errors": 0, "latency_ms_median": 900, "latency_ms_p90": 1500,
              "cost_usd": 0.001, "by_release": {"r1": {"requests": 3}}}
    client.mp.setattr(logging_store, "status_windows", lambda: {"last_24h": window, "last_7d": window})
    client.mp.setattr(logging_store, "spent_today", lambda: 0.123)
    j = client.get("/status").json()
    assert j["last_24h"]["requests"] == 3 and j["last_7d"]["by_release"]["r1"]["requests"] == 3
    assert j["budget_today"]["used_usd"] == 0.123 and j["budget_today"]["limit_usd"] == 0.5
    assert "question" not in str(j)


def test_status_503_when_log_down(client):
    def boom():
        raise ConnectionError
    client.mp.setattr(logging_store, "status_windows", boom)
    assert client.get("/status").status_code == 503


# ---- logging store ----
def test_log_request_never_raises(monkeypatch, capsys):
    monkeypatch.setattr(logging_store.db, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setenv("HQ_LOG_URL", "postgresql://x")
    logging_store.log_request(None, "h", "r", error="e", question="q")
    assert "request-log write failed" in capsys.readouterr().err


def test_build_row_maps_answer_fields():
    a = pipeline.Answer(question="q", route="data", refused=False, prompt_versions={"plan": "p"}, sql="select 1",
                        row_count=2, model="m", total_input_tokens=10, total_output_tokens=5, total_cost_usd=0.001,
                        timings={"total_ms": 1234, "plan_ms": 5}, retrieved_chunk_ids=["a"],
                        citations=[pipeline.Citation(chunk_id="a", doc_title="d", quote="x")])
    row = logging_store.build_row(a, "hash", "rel")
    assert row[0] == "rel" and row[1] == "hash" and row[2] == "q" and row[8] == ["a"] and row[9] == ["a"]
    assert row[15] == 1234 and len(row) == 20


# ---- prompt version switches ----
def test_prompt_versions_default_and_env(monkeypatch):
    assert pipeline.prompt_versions() == {"plan": "plan_v4", "schema": "schema_v2", "answer": "answer_v4"}
    monkeypatch.setenv("HQ_PLAN_PROMPT", "plan_v3")
    monkeypatch.setenv("HQ_ANSWER_PROMPT", "answer_v3")
    monkeypatch.setenv("HQ_SCHEMA_PROMPT", "schema_v1")
    assert pipeline.prompt_versions() == {"plan": "plan_v3", "schema": "schema_v1", "answer": "answer_v3"}


@pytest.mark.parametrize("var", ["HQ_PLAN_PROMPT", "HQ_ANSWER_PROMPT", "HQ_SCHEMA_PROMPT"])
def test_unknown_prompt_name_raises_clear_error_before_any_model_call(monkeypatch, var):
    monkeypatch.setenv(var, "nope_v9")

    class NoLLM:
        def complete(self, *a, **k):
            raise AssertionError("model must not be called")
    with pytest.raises(FileNotFoundError, match="nope_v9"):
        pipeline.ask("q", llm=NoLLM(), embedder=None)


def test_env_prompt_versions_are_what_ask_reports(monkeypatch):
    monkeypatch.setenv("HQ_PLAN_PROMPT", "plan_v3")
    monkeypatch.setenv("HQ_SCHEMA_PROMPT", "schema_v1")

    class Refuser:
        def complete(self, system, user, schema, model=None):
            from service.llm import Usage
            return pipeline.Plan(route="refuse", reason="no"), Usage(1, 1, 0.0, 1, "m")
    a = pipeline.ask("q", llm=Refuser())
    assert a.prompt_versions["plan"] == "plan_v3" and a.prompt_versions["schema"] == "schema_v1"
