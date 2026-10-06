"""Offline structure checks on evals/questions_holdout_v1.jsonl (no database, no network).

The database-backed checks (truth queries run, row counts, determinism, absent-term search, and the
no-overlap-with-v1 checks) live in evals/make_questions_holdout_v1.py, which must pass before the file is written.
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

HOLDOUT = ROOT / "evals" / "questions_holdout_v1.jsonl"
V1 = ROOT / "evals" / "questions_v1.jsonl"
CHUNKS = ROOT / "docs_index" / "chunks.jsonl"

BASE = ["id", "type", "split", "difficulty", "question", "author"]
REQUIRED = {
    "numeric": ["truth_sql", "key_column", "value_columns", "expected_row_count", "expected_rows", "measure_ids"],
    "definition": ["expected_chunk_ids", "expected_doc_ids", "answer_points"],
    "definition_unanswerable": ["expected", "why", "absent_patterns"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def _load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def qs():
    assert HOLDOUT.exists(), "run evals/make_questions_holdout_v1.py first"
    return _load(HOLDOUT)


@pytest.fixture(scope="module")
def chunks():
    return {c["chunk_id"]: c for c in _load(CHUNKS)}


def test_ids_counts_and_split(qs):
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids))
    assert Counter(q["type"] for q in qs) == {"numeric": 8, "definition": 15, "definition_unanswerable": 3}
    assert {q["split"] for q in qs} == {"holdout"}
    assert {q["author"] for q in qs} == {"claude"}
    assert {q["id"] for q in qs if q["type"] == "definition"} == {f"hdef-{i:02d}" for i in range(1, 16)}
    assert {q["id"] for q in qs if q["type"] == "definition_unanswerable"} == {f"hdefx-{i:02d}" for i in range(1, 4)}
    assert {q["id"] for q in qs if q["type"] == "numeric"} == {f"hnum-{i:02d}" for i in range(1, 9)}
    assert Counter(q["difficulty"] for q in qs if q["type"] == "numeric") == {"easy": 3, "medium": 3, "hard": 2}


def test_required_fields(qs):
    for q in qs:
        for f in BASE + REQUIRED[q["type"]]:
            assert f in q, f"{q['id']} missing {f}"
        assert q["difficulty"] in ("easy", "medium", "hard") and q["question"].strip(), q["id"]
        if q["type"] == "definition_unanswerable":
            assert q["expected"] == "refuse", q["id"]


def test_numeric_sql_passes_guard(qs):
    for q in qs:
        if q["type"] == "numeric":
            check(q["truth_sql"])
            assert 1 <= q["expected_row_count"] <= 50, q["id"]
            assert len(q["expected_rows"]) == min(q["expected_row_count"], 20), q["id"]
            assert q["value_columns"], q["id"]
            if q["expected_row_count"] > 1:
                assert re.search(r"order\s+by", q["truth_sql"], re.I), q["id"]


def test_definition_chunks_and_evidence(qs, chunks):
    for q in qs:
        if q["type"] != "definition":
            continue
        assert 1 <= len(q["expected_chunk_ids"]) <= 3, q["id"]
        assert all(c in chunks for c in q["expected_chunk_ids"]), q["id"]
        assert q["expected_doc_ids"] == sorted({chunks[c]["doc_id"] for c in q["expected_chunk_ids"]}), q["id"]
        assert 2 <= len(q["answer_points"]) <= 3, q["id"]
        hay = [_norm(chunks[c]["text"]) for c in q["expected_chunk_ids"]]
        for p in q["answer_points"]:
            ev = _norm(p["evidence"])
            assert ev and any(ev in h for h in hay), f"{q['id']}: evidence not found: {p['evidence'][:60]!r}"


def test_every_document_covered(qs, chunks):
    docs = {c["doc_id"] for c in chunks.values()}
    counts = Counter(d for q in qs if q["type"] == "definition" for d in q["expected_doc_ids"])
    for d in docs:
        assert counts[d] >= 1, f"{d} has no holdout definition question"


def test_unanswerable_patterns_absent(qs, chunks):
    for q in qs:
        if q["type"] == "definition_unanswerable":
            for pat in q["absent_patterns"]:
                rx = re.compile(pat, re.I)
                assert not any(rx.search(re.sub(r"\s+", " ", c["text"])) for c in chunks.values()), f"{q['id']}: {pat}"


def test_no_overlap_with_v1(qs):
    v1 = _load(V1)
    v1_chunks = {c for q in v1 if q["type"] == "definition" for c in q["expected_chunk_ids"]}
    v1_text = {_norm(q["question"]) for q in v1}
    for q in qs:
        assert _norm(q["question"]) not in v1_text, q["id"]
        if q["type"] == "definition":
            assert not set(q["expected_chunk_ids"]) & v1_chunks, q["id"]
    assert {q["id"] for q in qs}.isdisjoint({q["id"] for q in v1})
