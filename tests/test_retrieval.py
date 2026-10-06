"""Retrieval fusion and keyword-query options: offline, with a fake database cursor."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import db, retrieval  # noqa: E402


class FakeCursor:
    """Answers each query by its SQL text from `data`: 'vector', 'and', 'or', 'sim', 'fetch'."""

    def __init__(self, data):
        self.data, self.queries, self._rows = data, [], []

    def execute(self, sql, params=None):
        if "websearch_to_tsquery" in sql:
            key = "and"
        elif "plainto_tsquery" in sql:
            key = "or"
        elif "<=>" in sql and "limit" in sql:
            key = "vector"
        elif "<=>" in sql:
            key = "sim"
        else:
            key = "fetch"
        self.queries.append(key)
        self._rows = self.data[key]

    def fetchall(self):
        return self._rows


def test_fuse_equal_weight_matches_plain_rrf():
    s = retrieval.fuse(["a", "b"], ["b", "c"])
    assert s["a"] == pytest.approx(1 / 61)
    assert s["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert s["c"] == pytest.approx(1 / 62)


def test_fuse_keyword_weight_scales_only_the_keyword_leg():
    s = retrieval.fuse(["a", "b"], ["b", "c"], keyword_weight=0.5)
    assert s["a"] == pytest.approx(1 / 61)
    assert s["b"] == pytest.approx(1 / 62 + 0.5 / 61)
    assert s["c"] == pytest.approx(0.5 / 62)
    assert retrieval.fuse(["a"], ["b"], keyword_weight=0.0)["b"] == 0.0


def test_weight_can_flip_a_rank_order():
    vec, kw = ["v1", "v2"], ["k1"]
    rank = lambda w: sorted(retrieval.fuse(vec, kw, w), key=retrieval.fuse(vec, kw, w).get, reverse=True)  # noqa: E731
    assert rank(1.0) == ["v1", "k1", "v2"]
    assert rank(0.25) == ["v1", "v2", "k1"]


def test_and_first_uses_all_words_when_enough_rows():
    cur = FakeCursor({"and": [("a",), ("b",), ("c",)], "or": [("z",)]})
    assert retrieval.keyword_ids(cur, "q", "and_first") == ["a", "b", "c"]
    assert cur.queries == ["and"]


def test_and_first_falls_back_to_or_below_three_rows():
    cur = FakeCursor({"and": [("a",), ("b",)], "or": [("x",), ("y",)]})
    assert retrieval.keyword_ids(cur, "q", "and_first") == ["x", "y"]
    assert cur.queries == ["and", "or"]


def test_or_query_never_runs_the_and_query():
    cur = FakeCursor({"and": [("a",)] * 5, "or": [("x",)]})
    assert retrieval.keyword_ids(cur, "q", "or") == ["x"]
    assert cur.queries == ["or"]


def test_unknown_keyword_query_rejected():
    with pytest.raises(ValueError):
        retrieval.keyword_ids(FakeCursor({}), "q", "nope")


def test_frozen_defaults():
    assert (retrieval.DEFAULT_K, retrieval.DEFAULT_KEYWORD_WEIGHT, retrieval.DEFAULT_KEYWORD_QUERY) == (8, 0.5, "and_first")
    import inspect
    p = inspect.signature(retrieval.search_docs).parameters
    assert p["k"].default == 8 and p["keyword_weight"].default == 0.5 and p["keyword_query"].default == "and_first"
    assert p["mode"].default == "vector" == retrieval.DEFAULT_MODE


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self.cur


class _Emb:
    model, dims = "fake", 3

    def encode(self, texts):
        return [[0.0, 0.0, 1.0] for _ in texts]


def _search(monkeypatch, **kw):
    row = lambda cid: (cid, "Doc", "Sec", 1, "http://x", "body " + cid)  # noqa: E731
    cur = FakeCursor({"vector": [("v1", 0.9), ("v2", 0.8), ("v3", 0.7)], "and": [("k1",)], "or": [("k1",), ("v3",)],
                      "sim": [("k1", 0.5)], "fetch": [row(c) for c in ("v1", "v2", "v3", "k1")]})
    monkeypatch.setenv("HQ_SERVICE_URL", "postgresql://x")
    db.close_all()
    monkeypatch.setattr(db, "_connect", lambda url: _Conn(cur))
    return cur, retrieval.search_docs("question", embedder=_Emb(), **kw)


def test_search_docs_default_mode_is_vector(monkeypatch):
    cur, out = _search(monkeypatch)
    assert cur.queries == ["vector", "fetch"]


def test_search_docs_hybrid_default_weight_and_query(monkeypatch):
    cur, out = _search(monkeypatch, mode="hybrid")
    assert cur.queries[:3] == ["vector", "and", "or"]  # and-first, 1 row < 3, falls back to OR
    top = [c.chunk_id for c in out]
    # v3 is in both lists; with keyword weight 0.5 it still beats k1
    assert top.index("v3") < top.index("k1")


def test_search_docs_explicit_options_and_vector_mode(monkeypatch):
    cur, out = _search(monkeypatch, mode="hybrid", keyword_weight=1.0, keyword_query="or")
    assert "and" not in cur.queries
    cur, out = _search(monkeypatch, mode="vector")
    assert cur.queries == ["vector", "fetch"]
    with pytest.raises(ValueError):
        retrieval.search_docs("q", embedder=_Emb(), mode="bad")


# ---- collection filter ----
class RecordingCursor(FakeCursor):
    def execute(self, sql, params=None):
        super().execute(sql, params)
        self.params = getattr(self, "params", []) + [params]
        self.sqls = getattr(self, "sqls", []) + [sql]


def _search_rec(monkeypatch, **kw):
    row = lambda cid: (cid, "Doc", "Sec", None, "http://x", "body " + cid)  # noqa: E731
    cur = RecordingCursor({"vector": [("v1", 0.9), ("v2", 0.8)], "and": [("k1",)], "or": [("k1",)],
                           "sim": [("k1", 0.5)], "fetch": [row(c) for c in ("v1", "v2", "k1")]})
    monkeypatch.setenv("HQ_SERVICE_URL", "postgresql://x")
    db.close_all()
    monkeypatch.setattr(db, "_connect", lambda url: _Conn(cur))
    return cur, retrieval.search_docs("question", embedder=_Emb(), **kw)


@pytest.mark.parametrize("mode", ["vector", "hybrid", "keyword"])
def test_every_query_filters_by_collection(monkeypatch, mode):
    cur, _ = _search_rec(monkeypatch, mode=mode, collection="coverage")
    assert cur.sqls and all("collection = %(c)s" in s for s in cur.sqls)
    assert all(p["c"] == "coverage" for p in cur.params)


def test_default_collection_is_measures(monkeypatch):
    import inspect
    assert inspect.signature(retrieval.search_docs).parameters["collection"].default == "measures"
    cur, _ = _search_rec(monkeypatch)
    assert all(p["c"] == "measures" for p in cur.params)


def test_unknown_collection_rejected(monkeypatch):
    with pytest.raises(ValueError):
        retrieval.search_docs("q", embedder=_Emb(), collection="lcd")
