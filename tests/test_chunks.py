"""Sanity checks over docs_index/chunks.jsonl (built by docs_index/chunk.py)."""
import json
from pathlib import Path

import pytest

IDX = Path(__file__).resolve().parents[1] / "docs_index"
CHUNKS = IDX / "chunks.jsonl"
MANIFEST = IDX / "manifest.json"

pytestmark = pytest.mark.skipif(not CHUNKS.exists(), reason="run docs_index/chunk.py first")


@pytest.fixture(scope="module")
def chunks():
    return [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_not_empty(chunks):
    assert len(chunks) > 0


def test_unique_chunk_ids(chunks):
    ids = [c["chunk_id"] for c in chunks]
    assert len(ids) == len(set(ids))


def test_chunk_id_format(chunks):
    for c in chunks:
        assert c["chunk_id"].startswith(c["doc_id"] + ":")
        assert c["chunk_id"].rsplit(":", 1)[1].isdigit()


def test_no_empty_text(chunks):
    assert all(c["text"].strip() for c in chunks)


def test_required_fields_present(chunks):
    for c in chunks:
        for k in ("doc_id", "source_url", "section_title"):
            assert isinstance(c.get(k), str) and c[k].strip(), (c["chunk_id"], k)


def test_n_chars_matches_text(chunks):
    bad = [c["chunk_id"] for c in chunks if c["n_chars"] != len(c["text"])]
    assert not bad, bad[:5]


def test_no_chunk_over_4000(chunks):
    big = [(c["chunk_id"], c["n_chars"]) for c in chunks if c["n_chars"] > 4000]
    assert not big, big[:5]


def test_page_range_sane(chunks):
    for c in chunks:
        if c["page_start"] is not None:
            assert 1 <= c["page_start"] <= c["page_end"], c["chunk_id"]


def test_every_manifest_doc_has_chunks(chunks):
    docs = json.loads(MANIFEST.read_text(encoding="utf-8"))["documents"]
    have = {c["doc_id"] for c in chunks}
    missing = [d["doc_id"] for d in docs if d["doc_id"] not in have]
    assert not missing, missing
