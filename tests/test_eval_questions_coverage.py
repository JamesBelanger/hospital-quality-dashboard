"""Offline checks on evals/questions_coverage_v1.jsonl and docs_index/chunks_ncd.jsonl (no database, no network).

The verification that writes the question file (evidence quotes, absent terms) lives in
evals/make_questions_coverage_v1.py; these tests re-check the written file, and that the file is the frozen one.
"""
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QS = ROOT / "evals" / "questions_coverage_v1.jsonl"
NCD = ROOT / "docs_index" / "chunks_ncd.jsonl"
MANIFEST = ROOT / "docs_index" / "manifest_ncd.json"
FROZEN_SHA256 = "1a62f8a53c4172c4a596d2e994d4247cefc07f615943e692207fc126cc988e23"  # see evals/README.md Decisions log


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def _load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.fixture(scope="module")
def qs():
    return _load(QS)


@pytest.fixture(scope="module")
def chunks():
    return _load(NCD)


def test_question_file_is_the_frozen_one():
    assert hashlib.sha256(QS.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == FROZEN_SHA256


def test_counts_ids_and_split(qs):
    assert Counter(q["type"] for q in qs) == {"definition": 22, "definition_unanswerable": 4, "out_of_scope": 3, "unsafe": 1}
    ids = [q["id"] for q in qs]
    assert len(ids) == len(set(ids)) == 30
    dev = {q["id"] for q in qs if q["split"] == "dev"}
    assert dev == {f"cov-0{i}" for i in range(1, 7)} | {"covx-01", "covo-01"}
    assert {q["split"] for q in qs} == {"dev", "test"} and {q["author"] for q in qs} == {"claude"}
    assert sum(q["split"] == "test" for q in qs) == 22


def test_definition_questions_point_at_real_ncd_chunks(qs, chunks):
    by_id = {c["chunk_id"]: c for c in chunks}
    for q in (q for q in qs if q["type"] == "definition"):
        assert 1 <= len(q["expected_chunk_ids"]) <= 3 and 2 <= len(q["answer_points"]) <= 3, q["id"]
        assert all(c in by_id and by_id[c]["collection"] == "coverage" for c in q["expected_chunk_ids"]), q["id"]
        assert q["expected_doc_ids"] == sorted({c.rsplit(":", 1)[0] for c in q["expected_chunk_ids"]}), q["id"]
        for p in q["answer_points"]:
            assert any(_norm(p["evidence"]) in _norm(by_id[c]["text"]) for c in q["expected_chunk_ids"]), (q["id"], p["evidence"])


def test_unanswerable_terms_absent_from_every_ncd_chunk(qs, chunks):
    for q in (q for q in qs if q["type"] == "definition_unanswerable"):
        for pat in q["absent_patterns"]:
            assert not any(re.search(pat, c["text"], re.I) for c in chunks), (q["id"], pat)


def test_declined_questions_expect_refusal(qs):
    for q in (q for q in qs if q["type"] in ("out_of_scope", "unsafe", "definition_unanswerable")):
        assert q["expected"] == "refuse" and q["question"].strip(), q["id"]


# ---- the NCD chunk file ----
def test_ncd_chunks_follow_the_size_and_naming_rules(chunks):
    assert len(chunks) > 300
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))
    for c in chunks:
        assert c["collection"] == "coverage" and c["doc_id"].startswith("ncd_")
        assert c["chunk_id"].startswith(c["doc_id"] + ":") and c["chunk_id"].rsplit(":", 1)[1].isdigit()
        assert re.match(r"NCD \S+ .+ — ", c["section_title"]), c["section_title"]
        assert c["source_url"].startswith("https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid=")
        assert 0 < len(c["text"]) <= 4000 and "�" not in c["text"]
    assert max(len(c["text"]) for c in chunks) <= 2800  # same 2,400 target with the tail-fold allowance


def test_manifest_records_every_ncd():
    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    docs = m["documents"]
    assert len(docs) == len({d["doc_id"] for d in docs}) > 300 and not m["problems"]
    for d in docs:
        for k in ("ncd_id", "manual_section", "title", "version", "effective_date", "source_url", "retrieved_at", "sha256"):
            assert d.get(k), (d["doc_id"], k)
        assert re.fullmatch(r"[0-9a-f]{64}", d["sha256"])
