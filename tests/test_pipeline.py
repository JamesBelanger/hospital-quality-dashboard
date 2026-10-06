"""ask() with a fake model, fake embedder and stubbed retrieval / SQL runner: no network.

Live end-to-end tests run only when HQ_LIVE=1.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import pipeline, retrieval  # noqa: E402
from service.llm import Usage  # noqa: E402
from service.retrieval import Chunk  # noqa: E402
from service.sql_runner import DatabaseError, GuardRejected, SqlResult  # noqa: E402


class FakeLLM:
    """Replies with queued objects in order; records every call."""

    def __init__(self, *replies):
        self.replies, self.calls, self.models = list(replies), [], []

    def complete(self, system, user, schema, model=None):
        self.calls.append((schema.__name__, user))
        self.models.append(model)
        obj = self.replies.pop(0)
        assert isinstance(obj, schema)
        return obj, Usage(100, 20, 0.00002, 5, "fake-model")


class FakeEmbedder:
    model, dims = "fake", 3

    def encode(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]


BODY = "A readmission is an unplanned return to a hospital within 30 days of discharge."


def chunk(sim=0.8, cid="c1", body=BODY):
    return Chunk(cid, "Measure methodology", "Readmission", 4, "http://x/doc", body, sim, 0.03)


def result(rows=((1, "A"),)):
    return SqlResult("SELECT 1 LIMIT 200", ["n", "name"], [list(r) for r in rows], len(rows), 3)


def plan(route, sql=None, doc_query=None):
    return pipeline.Plan(route=route, sql=sql, doc_query=doc_query, reason="because")


def answer(text="Hospital A.", cites=(), supported=True):
    return pipeline.AnswerOut(answer=text, citations=[pipeline.CitationIn(chunk_id=c, quote=q) for c, q in cites],
                              supported=supported)


@pytest.fixture()
def stubs(monkeypatch):
    """Record SQL/search calls; tests set `.sql_results` / `.chunks`."""
    class S:
        sql_results = [result()]
        chunks = [chunk()]
        sql_calls, search_calls, search_modes = [], [], []

    def fake_run(sql):
        S.sql_calls.append(sql)
        r = S.sql_results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def fake_search(q, k=6, embedder=None, mode="hybrid"):
        S.search_calls.append(q)
        S.search_modes.append(mode)
        return S.chunks

    S.sql_calls, S.search_calls, S.search_modes = [], [], []
    monkeypatch.setattr(pipeline, "run_sql", fake_run)
    monkeypatch.setattr(pipeline, "search_docs", fake_search)
    return S


def test_refuse_route_makes_no_further_calls(stubs):
    llm = FakeLLM(plan("refuse"))
    a = pipeline.ask("What is the weather?", llm=llm, embedder=FakeEmbedder())
    assert a.refused and a.refusal_reason
    assert len(llm.calls) == 1 and not stubs.sql_calls and not stubs.search_calls
    assert a.total_input_tokens == 100


def test_unsafe_sql_gets_exactly_one_repair_then_gives_up(stubs):
    stubs.sql_results = [GuardRejected("table x is not available"), GuardRejected("table y is not available")]
    llm = FakeLLM(plan("data", sql="select * from x"), plan("data", sql="select * from y"))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert a.refused and a.repaired
    assert [c[0] for c in llm.calls] == ["Plan", "Plan"]  # plan + one repair, no answer call
    assert len(stubs.sql_calls) == 2
    assert "table x is not available" in llm.calls[1][1] and "select * from x" in llm.calls[1][1]


def test_repair_that_works_is_answered(stubs):
    stubs.sql_results = [DatabaseError('column "nope" does not exist'), result()]
    llm = FakeLLM(plan("data", sql="select nope"), plan("data", sql="select 1"), answer())
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and a.repaired and stubs.sql_calls == ["select nope", "select 1"]


def test_low_similarity_refuses_docs_question(stubs):
    stubs.chunks = [chunk(sim=0.13)]
    llm = FakeLLM(plan("docs", doc_query="readmission"))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert a.refused and len(llm.calls) == 1


def test_keyword_only_match_is_not_support(stubs):
    stubs.chunks = [chunk(sim=None)]
    a = pipeline.ask("q", llm=FakeLLM(plan("docs", doc_query="x")), embedder=FakeEmbedder())
    assert a.refused


def test_fabricated_citation_is_dropped(stubs):
    quote = "unplanned return to a hospital within 30 days"
    llm = FakeLLM(plan("docs", doc_query="readmission"), answer("It is a return within 30 days.", cites=[
        ("c1", quote.upper().replace(" ", "  ")),  # same text, different case and spacing: kept
        ("c1", "a quote the document never says"),
        ("zzz", quote),  # unknown chunk id
    ]))
    a = pipeline.ask("What is a readmission?", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and len(a.citations) == 1
    assert a.citations[0].chunk_id == "c1" and a.citations[0].page_start == 4


def test_docs_only_answer_without_valid_citation_is_refused(stubs):
    llm = FakeLLM(plan("docs", doc_query="readmission"), answer("Invented.", cites=[("c1", "not in the text")]))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert a.refused and not a.citations


def test_unsupported_flag_refuses(stubs):
    llm = FakeLLM(plan("data", sql="select 1"), answer("No hospital matches.", supported=False))
    assert pipeline.ask("q", llm=llm, embedder=FakeEmbedder()).refused


def test_data_answer_passes_rows_through(stubs):
    stubs.sql_results = [result([(i, f"H{i}") for i in range(80)])]
    llm = FakeLLM(plan("data", sql="select 1"), answer("Hospital H0 is first."))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and a.answer == "Hospital H0 is first."
    assert a.sql == "SELECT 1 LIMIT 200" and a.columns == ["n", "name"]
    assert len(a.rows) == 50 and a.row_count == 80
    assert not stubs.search_calls
    assert a.prompt_versions["plan"] == pipeline.PLAN_PROMPT
    assert a.total_input_tokens == 200 and [u.step for u in a.usage] == ["plan", "answer"]
    assert "first 50 of 80" in llm.calls[1][1]


def test_empty_result_is_answered_as_none_match(stubs):
    # A query that ran and matched nothing is evidence ("no hospital meets the condition"), not a failure.
    stubs.sql_results = [result([])]
    llm = FakeLLM(plan("data", sql="select 1"), plan("data", sql="select 1"), answer("No hospitals in this dataset match."))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and a.row_count == 0 and a.rows == [] and a.sql
    assert "returned 0 rows" in llm.calls[2][1]


def test_retrieved_ids_and_top_similarity_recorded_even_when_refused(stubs):
    stubs.chunks = [chunk(sim=0.13, cid="a"), chunk(sim=0.10, cid="b")]
    a = pipeline.ask("q", llm=FakeLLM(plan("docs", doc_query="x")), embedder=FakeEmbedder())
    assert a.refused and a.retrieved_chunk_ids == ["a", "b"] and a.doc_top_similarity == 0.13


def test_retrieved_ids_recorded_on_answered_docs_question(stubs):
    stubs.chunks = [chunk(cid="a"), chunk(sim=0.5, cid="b")]
    llm = FakeLLM(plan("docs", doc_query="x"), answer("ok", cites=[("a", "unplanned return to a hospital")]))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and a.retrieved_chunk_ids == ["a", "b"] and a.doc_top_similarity == 0.8


def test_data_only_answer_has_no_retrieval_fields(stubs):
    a = pipeline.ask("q", llm=FakeLLM(plan("data", sql="select 1"), answer()), embedder=FakeEmbedder())
    assert a.retrieved_chunk_ids == [] and a.doc_top_similarity is None


def test_retrieval_mode_comes_from_env(stubs, monkeypatch):
    monkeypatch.setenv("HQ_RETRIEVAL_MODE", "keyword")
    pipeline.ask("q", llm=FakeLLM(plan("docs", doc_query="x"), answer(supported=False)), embedder=FakeEmbedder())
    monkeypatch.delenv("HQ_RETRIEVAL_MODE")
    pipeline.ask("q", llm=FakeLLM(plan("docs", doc_query="x"), answer(supported=False)), embedder=FakeEmbedder())
    assert stubs.search_modes == ["keyword", retrieval.DEFAULT_MODE]


def test_model_override_is_passed_to_every_llm_call(stubs):
    stubs.sql_results = [DatabaseError("bad"), result()]
    llm = FakeLLM(plan("data", sql="s1"), plan("data", sql="s2"), answer())
    pipeline.ask("q", llm=llm, embedder=FakeEmbedder(), model="gpt-6-sol")
    assert llm.models == ["gpt-6-sol"] * 3
    llm2 = FakeLLM(plan("refuse"))
    pipeline.ask("q", llm=llm2, embedder=FakeEmbedder())
    assert llm2.models == [None]


@pytest.mark.skipif(os.environ.get("HQ_LIVE") != "1", reason="set HQ_LIVE=1 to call OpenAI and the database")
def test_live_refusal_and_data():
    a = pipeline.ask("What is the capital of France?")
    assert a.refused
    b = pipeline.ask("How many hospitals are in Texas?")
    assert not b.refused and b.rows


# ---- empty-result check (one repair per question, of either kind) ----
def test_empty_result_corrected_sql_returns_rows(stubs):
    stubs.sql_results = [result([]), result([(1, "A")])]
    llm = FakeLLM(plan("data", sql="select 1 where x = 'a'"), plan("data", sql="select 1 where upper(x) = 'A'"),
                  answer("Hospital A."))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and a.repaired and a.repair_kind == "empty" and a.row_count == 1
    assert stubs.sql_calls == ["select 1 where x = 'a'", "select 1 where upper(x) = 'A'"]
    assert "returned 0 rows" in llm.calls[1][1] and "select 1 where x = 'a'" in llm.calls[1][1]
    assert [u.step for u in a.usage] == ["plan", "empty_check_changed", "answer"]


def test_empty_result_same_sql_is_answered_as_none(stubs):
    stubs.sql_results = [result([])]
    llm = FakeLLM(plan("data", sql="select 1"), plan("data", sql="select 1"), answer("No hospitals match."))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and a.row_count == 0 and a.repair_kind == "empty" and a.repaired
    assert stubs.sql_calls == ["select 1"]  # the unchanged SQL is not run again
    assert "returned 0 rows" in llm.calls[2][1]
    assert [u.step for u in a.usage] == ["plan", "empty_check", "answer"]


def test_empty_corrected_sql_that_fails_keeps_the_zero_row_answer(stubs):
    stubs.sql_results = [result([]), DatabaseError("boom")]
    llm = FakeLLM(plan("data", sql="s1"), plan("data", sql="s2"), answer("No hospitals match."))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and a.row_count == 0 and a.repair_kind == "empty" and len(llm.calls) == 3


def test_error_repair_already_used_means_no_empty_check(stubs):
    stubs.sql_results = [DatabaseError("bad"), result([])]
    llm = FakeLLM(plan("data", sql="s1"), plan("data", sql="s2"), answer("No hospitals match."))
    a = pipeline.ask("q", llm=llm, embedder=FakeEmbedder())
    assert not a.refused and a.row_count == 0 and a.repair_kind == "error"
    assert [c[0] for c in llm.calls] == ["Plan", "Plan", "AnswerOut"]  # no second plan-style call


def test_non_empty_result_has_no_repair_kind(stubs):
    a = pipeline.ask("q", llm=FakeLLM(plan("data", sql="select 1"), answer()), embedder=FakeEmbedder())
    assert a.repair_kind is None and not a.repaired


def test_doc_query_recorded_planner_rewrite_or_question(stubs):
    stubs.chunks = [chunk(sim=0.1)]  # below the support threshold: refused, no answer call needed
    a = pipeline.ask("orig q", llm=FakeLLM(plan("docs", doc_query="rewritten")), embedder=FakeEmbedder())
    assert a.doc_query == "rewritten"
    a = pipeline.ask("orig q", llm=FakeLLM(plan("docs", doc_query=None)), embedder=FakeEmbedder())
    assert a.doc_query == "orig q"
    a = pipeline.ask("q", llm=FakeLLM(plan("refuse")), embedder=FakeEmbedder())
    assert a.doc_query is None
