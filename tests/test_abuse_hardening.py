"""Fixes from the first adversarial pass: evidence size, answer length, coverage closing sentence, per-URL locks,
the client-side query deadline, in-flight limits with real threads, and HTTP hygiene. All offline."""
import json
import sys
import threading
import time
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import api, db, limits, logging_store, pipeline, sql_runner  # noqa: E402
from service.sql_runner import SqlResult  # noqa: E402
from tests.test_pipeline import FakeEmbedder, FakeLLM, answer, chunk, plan, result  # noqa: E402,F401
from tests.test_pipeline import stubs, ncd_chunk  # noqa: E402,F401  (fixtures / helpers)


# ---- evidence size ----
def test_cap_result_cuts_cells_and_keeps_row_count():
    res = SqlResult("q", ["a", "b", "c"], [["x" * 1000, 5, ["y"] * 400]], 1, 1)
    out = pipeline.cap_result(res)
    assert out.rows[0][0] == "x" * 300 + "…[cut]" and out.rows[0][1] == 5
    assert isinstance(out.rows[0][2], str) and out.rows[0][2].endswith("[cut]") and out.row_count == 1


def test_rows_to_model_are_capped_at_12000_chars_and_the_model_is_told(stubs):
    rows = [(i, "z" * 300) for i in range(50)]  # 50 rows of about 320 chars: 16000 > 12000
    stubs.sql_results = [result(rows)]
    llm = FakeLLM(plan("data", sql="select 1"), answer("Many."))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    user = llm.calls[1][1]
    shown = len(a.rows)
    assert 0 < shown < 50 and a.row_count == 50
    assert f"showing the first {shown} of 50" in user
    assert len(json.dumps(a.rows)) <= pipeline.MAX_ROWS_CHARS


def test_long_cell_is_cut_in_the_answer_call_and_the_api_rows(stubs):
    stubs.sql_results = [result([(1, "q" * 5000)])]
    llm = FakeLLM(plan("data", sql="select 1"), answer("ok"))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert "q" * 5000 not in llm.calls[1][1] and a.rows[0][1].endswith("…[cut]") and len(a.rows[0][1]) < 320


def test_answer_call_has_a_max_output_token_cap(stubs):
    llm = FakeLLM(plan("data", sql="select 1"), answer("ok"))
    pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert dict(llm.max_tokens) == {"Plan": None, "AnswerOut": pipeline.ANSWER_MAX_OUTPUT_TOKENS}


def test_truncated_answer_reply_is_a_refusal_not_an_exception(stubs):
    class Truncating(FakeLLM):
        def complete(self, system, user, schema, model=None, max_output_tokens=None):
            if schema.__name__ == "AnswerOut":
                pipeline.AnswerOut.model_validate_json('{"answer":"cut off mid')  # what the SDK raises on a cut-off reply
            return super().complete(system, user, schema, model, max_output_tokens)
    a = pipeline.ask("q", llm=Truncating(plan("data", sql="select 1")), embedder=FakeEmbedder())
    assert a.refused and a.refusal_reason == pipeline.REFUSAL_TOO_LONG and a.row_count == 1


# ---- answer length ----
def test_cap_answer_cuts_at_sentence_end():
    text = "This is a sentence. " * 200
    out = pipeline.cap_answer(text)
    assert len(out) <= pipeline.MAX_ANSWER_CHARS + 5 and out.endswith("sentence. […]")
    assert pipeline.cap_answer("short.") == "short."
    assert pipeline.cap_answer("x" * 5000).endswith("[…]")  # no sentence end at all: hard cut


def test_long_answer_is_capped_in_ask(stubs):
    llm = FakeLLM(plan("data", sql="select 1"), answer("Hospital A is best. " * 300))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert len(a.answer) <= pipeline.MAX_ANSWER_CHARS + 5 and a.answer.endswith("[…]")


# ---- coverage closing sentence ----
def _coverage(stubs, text):
    stubs.chunks = [ncd_chunk()]
    llm = FakeLLM(plan("docs", doc_query="x", doc_collection="coverage"),
                  answer(text, cites=[("ncd_20.4:1", "ICDs are covered for patients with a prior MI")]))
    return pipeline.ask("q", llm=llm, embedder=FakeEmbedder())


def test_coverage_answer_gets_the_closing_sentence_when_missing(stubs):
    a = _coverage(stubs, "NCD 20.4 covers it.")
    assert a.answer == "NCD 20.4 covers it. " + pipeline.COVERAGE_CLOSING


def test_coverage_answer_with_closing_is_left_alone(stubs):
    text = "NCD 20.4 covers it. " + pipeline.COVERAGE_CLOSING
    assert _coverage(stubs, text).answer == text


def test_coverage_closing_is_never_cut_by_the_length_cap(stubs):
    a = _coverage(stubs, "NCD 20.4 covers it. " * 300)
    assert a.answer.endswith(pipeline.COVERAGE_CLOSING) and "[…]" in a.answer


def test_measures_answer_gets_no_closing(stubs):
    llm = FakeLLM(plan("docs", doc_query="readmission"), answer("ok", cites=[("c1", "unplanned return to a hospital")]))
    assert "coverage decision" not in pipeline.ask("q", llm=llm, embedder=FakeEmbedder()).answer


# ---- db: one lock per URL, acquire timeout ----
class _Conn:
    closed = False

    def cursor(self):
        return self

    def close(self):
        self.closed = True


@pytest.fixture()
def fakeconn(monkeypatch):
    db.close_all()
    monkeypatch.setattr(db, "_connect", lambda url: _Conn())
    yield
    db.close_all()


def test_slow_query_on_one_url_does_not_block_another(fakeconn):
    started, release_it = threading.Event(), threading.Event()

    def slow(cur):
        started.set()
        release_it.wait(5)

    t = threading.Thread(target=lambda: db.run("urlA", slow))
    t.start()
    assert started.wait(2)
    t0 = time.perf_counter()
    assert db.run("urlB", lambda cur: "fast") == "fast"
    assert time.perf_counter() - t0 < 1
    release_it.set()
    t.join(3)


def test_lock_wait_times_out_with_the_database_error_type(fakeconn):
    started, release_it = threading.Event(), threading.Event()
    t = threading.Thread(target=lambda: db.run("urlA", lambda cur: (started.set(), release_it.wait(5))))
    t.start()
    assert started.wait(2)
    with pytest.raises(psycopg.OperationalError, match="busy"):
        db.run("urlA", lambda cur: 1, lock_timeout=0.2)
    release_it.set()
    t.join(3)
    assert db.run("urlA", lambda cur: "ok") == "ok"  # the lock was not leaked


# ---- sql_runner: client-side deadline and fetch cap ----
class _SlowCursor:
    description = [type("D", (), {"name": "n"})()]

    def __init__(self, conn):
        self.connection = conn

    def execute(self, sql):
        self.connection.entered.set()
        if not self.connection.cancelled.wait(5):
            return
        raise psycopg.errors.QueryCanceled("canceled")

    def fetchmany(self, n):
        self.asked = n
        return [(i,) for i in range(n)]


class _SlowConn:
    closed = False

    def __init__(self):
        self.entered, self.cancelled = threading.Event(), threading.Event()
        self.cursor_obj = _SlowCursor(self)

    def cursor(self):
        return self.cursor_obj

    def cancel(self):
        self.cancelled.set()

    def close(self):
        self.closed = True


def test_query_past_the_deadline_is_cancelled_and_the_connection_discarded(monkeypatch):
    db.close_all()
    conn = _SlowConn()
    monkeypatch.setattr(db, "_connect", lambda url: conn)
    monkeypatch.setenv("HQ_READER_URL", "urlR")
    monkeypatch.setattr(sql_runner, "QUERY_DEADLINE_S", 0.2)
    t0 = time.perf_counter()
    with pytest.raises(sql_runner.DatabaseError, match="timeout|longer"):
        sql_runner.run_sql("select 1 from hq.hospitals")
    assert time.perf_counter() - t0 < 3 and conn.cancelled.is_set() and conn.closed
    assert "urlR" not in db._conns  # the next query opens a fresh connection


def test_fetch_asks_for_at_most_row_cap_plus_one(monkeypatch):
    db.close_all()
    conn = _SlowConn()
    conn.cancelled.set()  # not used: execute below returns at once
    cur = conn.cursor_obj
    cur.execute = lambda sql: None
    monkeypatch.setattr(db, "_connect", lambda url: conn)
    monkeypatch.setenv("HQ_READER_URL", "urlR2")
    res = sql_runner.run_sql("select 1 from hq.hospitals")
    assert cur.asked == sql_runner.sql_guard.MAX_ROWS + 1 and res.row_count == sql_runner.sql_guard.MAX_ROWS
    db.close_all()


# ---- limits: in-flight registry ----
@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("HQ_DAILY_BUDGET_USD", "HQ_CLIENT_PER_HOUR", "HQ_GLOBAL_PER_MINUTE", "HQ_MAX_INFLIGHT", "HQ_INFLIGHT_COST_USD"):
        monkeypatch.delenv(k, raising=False)
    limits._inflight.clear()
    yield
    limits._inflight.clear()


def test_inflight_counts_toward_the_hourly_limit():
    zero = lambda c: (0.0, 0, 0)  # noqa: E731
    tokens = [limits.admit("c", zero) for _ in range(6)]  # cap 6 in flight: raise it for this check
    assert len(tokens) == 6
    with pytest.raises(limits.LimitExceeded) as e:
        limits.admit("c", zero)
    assert e.value.status == 429 and e.value.retry_after_s == 5 and "busy" in e.value.detail


def test_inflight_per_client_and_budget_math(monkeypatch):
    monkeypatch.setenv("HQ_MAX_INFLIGHT", "50")
    monkeypatch.setenv("HQ_CLIENT_PER_HOUR", "3")
    zero = lambda c: (0.0, 0, 0)  # noqa: E731
    for _ in range(3):
        limits.admit("c", zero)
    with pytest.raises(limits.LimitExceeded, match="per hour"):
        limits.admit("c", zero)
    limits.admit("other", zero)  # a different client is unaffected
    assert limits.inflight_count() == 4  # the refused request did not stay registered
    monkeypatch.setenv("HQ_CLIENT_PER_HOUR", "99")
    monkeypatch.setenv("HQ_DAILY_BUDGET_USD", "0.10")
    monkeypatch.setenv("HQ_INFLIGHT_COST_USD", "0.02")
    limits._inflight.clear()
    for _ in range(4):
        limits.admit("c", lambda c: (0.0, 0, 0))
    # 4 others in flight x 0.02 = 0.08; plus 0.03 logged = 0.11 >= 0.10
    with pytest.raises(limits.LimitExceeded, match="budget"):
        limits.admit("d", lambda c: (0.03, 0, 0))


def test_global_per_minute_counts_inflight(monkeypatch):
    monkeypatch.setenv("HQ_MAX_INFLIGHT", "50")
    monkeypatch.setenv("HQ_GLOBAL_PER_MINUTE", "5")
    for i in range(5):
        limits.admit(f"c{i}", lambda c: (0.0, 0, 0))
    with pytest.raises(limits.LimitExceeded, match="minute"):
        limits.admit("z", lambda c: (0.0, 0, 0))


def test_release_frees_the_slot_and_is_idempotent():
    t = limits.admit("c", lambda c: (0.0, 0, 0))
    limits.release(t)
    limits.release(t)
    limits.release(None)
    assert limits.inflight_count() == 0


def test_a_check_failure_leaves_nothing_registered():
    def boom(c):
        raise ConnectionError("log down")
    with pytest.raises(limits.LimitExceeded) as e:
        limits.admit("c", boom)
    assert e.value.status == 503 and limits.inflight_count() == 0


# ---- API: simultaneous requests with real threads ----
@pytest.fixture()
def client(monkeypatch):
    logged = []
    state = {"calls": 0, "lock": threading.Lock(), "log": logged}
    monkeypatch.setattr(logging_store, "usage_snapshot", lambda c: (0.0, 0, 0))  # the log shows nothing: finishes are late
    monkeypatch.setattr(logging_store, "log_request", lambda *a, **k: logged.append(a))

    class Ans:
        def model_dump(self, mode="json"):
            return {"refused": False}

    def slow_ask(q):
        with state["lock"]:
            state["calls"] += 1
        time.sleep(0.6)
        return Ans()
    monkeypatch.setattr(pipeline, "ask", slow_ask)
    c = TestClient(api.app)
    c.state = state
    return c


def _burst(client, n, ip="9.9.9.9"):
    codes = []
    lock = threading.Lock()

    def one():
        r = client.post("/ask", json={"question": "How many hospitals?"}, headers={"X-Forwarded-For": ip})
        with lock:
            codes.append(r.status_code)
    threads = [threading.Thread(target=one) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    return codes


def test_30_simultaneous_requests_from_one_client_no_more_than_the_limit_proceed(client, monkeypatch):
    monkeypatch.setenv("HQ_MAX_INFLIGHT", "50")  # isolate the hourly limit from the busy cap
    codes = _burst(client, 30)
    assert len(codes) == 30 and codes.count(200) == 20 and codes.count(429) == 10
    assert client.state["calls"] == 20 and limits.inflight_count() == 0


def test_busy_cap_stops_a_burst_before_any_model_call(client):
    codes = _burst(client, 30)
    assert codes.count(200) <= 6 and codes.count(200) >= 1 and codes.count(200) + codes.count(429) == 30
    assert client.state["calls"] == codes.count(200)
    r = client.post("/ask", json={"question": "How many hospitals?"})  # all released: works again
    assert r.status_code == 200 and limits.inflight_count() == 0


def test_busy_response_has_retry_after_5(client):
    for i in range(6):
        limits.admit(f"c{i}", lambda c: (0.0, 0, 0))
    r = client.post("/ask", json={"question": "How many hospitals?"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "5" and not client.state["calls"]


def test_registration_released_when_ask_raises(client, monkeypatch):
    def bad(q):
        raise RuntimeError("x")
    monkeypatch.setattr(pipeline, "ask", bad)
    assert client.post("/ask", json={"question": "How many hospitals?"}).status_code == 502
    assert limits.inflight_count() == 0


# ---- HTTP hygiene ----
def test_docs_openapi_are_gone(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_validation_error_names_the_field_and_does_not_echo_input(client):
    secret = "LEAKME" + "x" * 300
    r = client.post("/ask", json={"question": secret})
    assert r.status_code == 422 and "question" in r.json()["detail"] and "LEAKME" not in r.text
    r = client.post("/ask", json={"nope": "LEAKME"})
    assert r.status_code == 422 and "question" in r.json()["detail"] and "LEAKME" not in r.text
    r = client.post("/ask", content="LEAKME{not json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and "LEAKME" not in r.text


def test_body_over_4kb_is_413_before_parsing(client):
    r = client.post("/ask", content=b"x" * 100_000, headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.headers["X-Release"] == api.RELEASE and not client.state["calls"]


def test_chunked_body_over_the_cap_is_413(client):
    def gen():
        for _ in range(10):
            yield b"x" * 1000  # no Content-Length: transfer-encoding chunked
    r = client.post("/ask", content=gen(), headers={"content-type": "application/json"})
    assert r.status_code == 413 and not client.state["calls"]


def test_ask_response_headers(client):
    r = client.post("/ask", json={"question": "How many hospitals?"})
    assert r.status_code == 200 and r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["Cache-Control"] == "no-store"
    assert "no-store" not in client.get("/health").headers.get("Cache-Control", "")
