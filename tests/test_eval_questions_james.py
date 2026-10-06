"""Offline structure checks on evals/questions_james.jsonl (no database, no network).

The database-backed checks (truth queries run, row counts, determinism, measure ids) live in
evals/make_questions_james_v1.py, which must pass before the file is written.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service.sql_guard import check  # noqa: E402

JAMES = ROOT / "evals" / "questions_james.jsonl"
PRIOR = [ROOT / "evals" / "questions_v1.jsonl", ROOT / "evals" / "questions_holdout_v1.jsonl"]
CHUNKS = ROOT / "docs_index" / "chunks.jsonl"

BASE = ["id", "type", "split", "difficulty", "question", "author", "approved_by", "provenance", "status", "overlaps"]
REQUIRED = {
    "numeric": ["truth_sql", "key_column", "value_columns", "expected_row_count", "expected_rows", "measure_ids"],
    "definition": ["expected_chunk_ids", "expected_doc_ids", "answer_points"],
    "out_of_scope": ["expected", "why"],
    "unsafe": ["expected", "why"],
}
PROVENANCE = ("AI-drafted (Astra), reviewed and approved by James 2026-10-06; "
              "ground truth added by a Claude worker")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def qs():
    assert JAMES.exists(), "run evals/make_questions_james_v1.py first"
    return _load(JAMES)


@pytest.fixture(scope="module")
def chunks():
    return {c["chunk_id"]: c for c in _load(CHUNKS)}


def test_ids_counts_and_provenance(qs):
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids))
    assert Counter(q["type"] for q in qs) == {"numeric": 12, "definition": 9, "out_of_scope": 2, "unsafe": 2}
    assert {q["id"] for q in qs if q["type"] == "numeric"} == {f"jnum-{i:02d}" for i in range(1, 13)}
    assert {q["id"] for q in qs if q["type"] == "definition"} == {f"jdef-{i:02d}" for i in range(1, 10)}
    assert {q["id"] for q in qs if q["type"] in ("out_of_scope", "unsafe")} == {f"joos-{i:02d}" for i in range(1, 5)}
    assert {q["split"] for q in qs} == {"holdout2"}
    assert {q["author"] for q in qs} == {"astra"}  # never "james": he approved, he did not write
    assert {q["approved_by"] for q in qs} == {"james"}
    assert {q["provenance"] for q in qs} == {PROVENANCE}
    assert Counter(q["difficulty"] for q in qs if q["type"] == "numeric") == {"easy": 4, "medium": 5, "hard": 3}


def test_required_fields_and_status(qs):
    for q in qs:
        for f in BASE + REQUIRED[q["type"]]:
            assert f in q, f"{q['id']} missing {f}"
        assert q["difficulty"] in ("easy", "medium", "hard") and q["question"].strip(), q["id"]
        assert q["status"] in ("ready", "needs_james"), q["id"]
        if q["status"] == "needs_james":
            assert q.get("notes") and q.get("proposed_rewording"), q["id"]
        if q["type"] in ("out_of_scope", "unsafe"):
            assert q["expected"] == "refuse" and q["why"].strip(), q["id"]
    assert {q["id"] for q in qs if q["status"] == "needs_james"} == {"jnum-08", "jnum-12"}


def test_numeric_sql_passes_guard(qs):
    for q in qs:
        if q["type"] == "numeric":
            check(q["truth_sql"])
            assert 1 <= q["expected_row_count"] <= 50, q["id"]
            assert len(q["expected_rows"]) == min(q["expected_row_count"], 20), q["id"]
            assert q["value_columns"], q["id"]
            if q["expected_row_count"] > 1:
                assert re.search(r"order\s+by", q["truth_sql"], re.I), q["id"]
            for m in q["measure_ids"]:
                assert m in q["truth_sql"], q["id"]


def test_definition_chunks_and_evidence(qs, chunks):
    for q in qs:
        if q["type"] != "definition":
            continue
        assert 1 <= len(q["expected_chunk_ids"]) <= 3, q["id"]
        assert all(c in chunks for c in q["expected_chunk_ids"]), q["id"]
        assert q["expected_doc_ids"] == sorted({chunks[c]["doc_id"] for c in q["expected_chunk_ids"]}), q["id"]
        assert 2 <= len(q["answer_points"]) <= 4, q["id"]
        hay = [_norm(chunks[c]["text"]) for c in q["expected_chunk_ids"]]
        for p in q["answer_points"]:
            ev = _norm(p["evidence"])
            assert ev and any(ev in h for h in hay), f"{q['id']}: evidence not found: {p['evidence'][:60]!r}"


def test_overlaps_reference_earlier_sets(qs):
    prior_ids = set()
    for p in PRIOR:
        prior_ids |= {r["id"] for r in _load(p)}
    for q in qs:
        assert isinstance(q["overlaps"], list), q["id"]
        assert set(q["overlaps"]) <= prior_ids, q["id"]
    assert {q["id"] for q in qs}.isdisjoint(prior_ids)
