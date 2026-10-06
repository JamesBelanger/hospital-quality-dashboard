"""Offline checks on evals/questions_v1.jsonl (no database, no network).

The database-backed checks (truth queries run, row counts, determinism) live in
evals/make_questions_v1.py, which must pass before the JSONL is written.
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

QUESTIONS = ROOT / "evals" / "questions_v1.jsonl"
CHUNKS = ROOT / "docs_index" / "chunks.jsonl"

BASE = ["id", "type", "split", "difficulty", "question", "author"]
REQUIRED = {
    "numeric": ["truth_sql", "key_column", "value_columns", "expected_row_count", "expected_rows", "measure_ids"],
    "definition": ["expected_chunk_ids", "expected_doc_ids", "answer_points"],
    "definition_unanswerable": ["expected", "why"],
    "out_of_scope": ["expected", "why"],
    "unsafe": ["expected", "why"],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


@pytest.fixture(scope="module")
def questions():
    assert QUESTIONS.exists(), "run evals/make_questions_v1.py first"
    return [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def chunks():
    out = {}
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            c = json.loads(line)
            out[c["chunk_id"]] = c
    return out


def test_ids_unique(questions):
    ids = [q["id"] for q in questions]
    assert len(ids) == len(set(ids))


def test_required_fields(questions):
    for q in questions:
        assert q["type"] in REQUIRED, q["id"]
        for f in BASE + REQUIRED[q["type"]]:
            assert f in q, f"{q['id']} missing {f}"
        assert q["difficulty"] in ("easy", "medium", "hard"), q["id"]
        assert q["split"] in ("dev", "test"), q["id"]
        assert q["author"] == "claude", q["id"]
        assert q["question"].strip(), q["id"]
        if q["type"] != "numeric" and q["type"] != "definition":
            assert q["expected"] == "refuse", q["id"]


def test_counts(questions):
    t = Counter(q["type"] for q in questions)
    assert t["numeric"] == 38
    assert t["definition"] == 22
    assert t["definition_unanswerable"] == 4
    assert t["out_of_scope"] + t["unsafe"] == 11
    assert Counter(q["split"] for q in questions)["dev"] == 12
    assert {q["id"] for q in questions if q["split"] == "dev"} == {f"seed-{i:02d}" for i in range(1, 13)}


def test_numeric_sql_passes_guard(questions):
    for q in questions:
        if q["type"] == "numeric":
            check(q["truth_sql"])  # raises UnsafeSQL on failure
            assert 1 <= q["expected_row_count"] <= 50, q["id"]
            assert len(q["expected_rows"]) == min(q["expected_row_count"], 20), q["id"]
            assert q["value_columns"], q["id"]


def test_chunk_ids_exist(questions, chunks):
    for q in questions:
        if q["type"] == "definition":
            assert 1 <= len(q["expected_chunk_ids"]) <= 3, q["id"]
            for cid in q["expected_chunk_ids"]:
                assert cid in chunks, f"{q['id']}: {cid}"
            assert q["expected_doc_ids"] == sorted({chunks[c]["doc_id"] for c in q["expected_chunk_ids"]}), q["id"]


def test_evidence_quotes_found(questions, chunks):
    for q in questions:
        if q["type"] == "definition":
            assert 2 <= len(q["answer_points"]) <= 4, q["id"]
            hay = [_norm(chunks[c]["text"]) for c in q["expected_chunk_ids"]]
            for p in q["answer_points"]:
                ev = _norm(p["evidence"])
                assert ev and any(ev in h for h in hay), f"{q['id']}: evidence not found: {p['evidence'][:60]!r}"


def test_every_document_covered(questions, chunks):
    docs = {c["doc_id"] for c in chunks.values()}
    counts = Counter(d for q in questions if q["type"] == "definition" for d in q["expected_doc_ids"])
    for d in docs:
        assert counts[d] >= 2, f"{d} has {counts[d]} definition questions"
