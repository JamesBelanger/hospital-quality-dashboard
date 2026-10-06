"""Hybrid retrieval over the documentation chunks in hq_docs.chunks.

Vector search (cosine, pgvector) and full-text search each return their top 20. The full-text
query (default "and_first") requires every word (`websearch_to_tsquery`) and, when that matches fewer
than 3 chunks, falls back to the question's meaningful terms joined with OR (`keyword_query="or"` uses
the OR query only), ranked by `ts_rank_cd`; a question with no meaningful term yields an empty keyword
list. The two lists are merged by reciprocal rank fusion (score = sum of weight / (60 + rank), keyword
weight 0.5 by default) and the best `k` are returned. Runs as the `hq_service`
login, which can read that one table and nothing else.

`top_similarity` is the best cosine similarity among the results; it is None when no
result came from the vector search, in which case the keyword match alone is not
treated as support.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

from service import db
from service.embedder import Embedder, OpenAIEmbedder, to_pgvector

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

RRF_K = 60
CANDIDATES = 20
# Defaults chosen from evals/results/retrieval_study_2026-10-06_planner_v4a.md: the same 22 definition questions, but
# scored on the queries the planner actually sends (not raw question text). On those, pure vector search beat every
# hybrid configuration (hit@6 17/22, MRR 0.573) and the pre-declared rule picked vector with k = 8. The earlier
# default (hybrid_and_first_w0.5, k = 6, retrieval_study_2026-10-06.md) was picked on raw question text. The hybrid
# and keyword modes and their parameters below still work; they are only no longer the default.
DEFAULT_MODE = "vector"
DEFAULT_K = 8
DEFAULT_KEYWORD_WEIGHT = 0.5
DEFAULT_KEYWORD_QUERY = "and_first"

_VECTOR_SQL = """
select chunk_id, 1 - (embedding <=> %(q)s::vector) as sim
from hq_docs.chunks where collection = %(c)s order by embedding <=> %(q)s::vector limit %(n)s"""
_TEXT_SQL = """
with q as (select replace(plainto_tsquery('english', %(t)s)::text, ' & ', ' | ')::tsquery as tq)
select chunk_id from hq_docs.chunks, q
where collection = %(c)s and q.tq::text <> '' and tsv @@ q.tq
order by ts_rank_cd(tsv, q.tq) desc, chunk_id limit %(n)s"""
_TEXT_AND_SQL = """
select chunk_id from hq_docs.chunks, websearch_to_tsquery('english', %(t)s) as tq
where collection = %(c)s and tq::text <> '' and tsv @@ tq
order by ts_rank_cd(tsv, tq) desc, chunk_id limit %(n)s"""
AND_FIRST_MIN_ROWS = 3  # keyword_query="and_first": fall back to the OR query below this many all-words matches
_SIM_SQL = """
select chunk_id, 1 - (embedding <=> %(q)s::vector) as sim
from hq_docs.chunks where collection = %(c)s and chunk_id = any(%(ids)s)"""
_FETCH_SQL = """
select chunk_id, doc_title, section_title, page_start, source_url, body
from hq_docs.chunks where collection = %(c)s and chunk_id = any(%(ids)s)"""


@dataclass
class Chunk:
    chunk_id: str
    doc_title: str
    section_title: str | None
    page_start: int | None
    source_url: str | None
    body: str
    vector_similarity: float | None
    fused_score: float


def top_similarity(chunks: list[Chunk]) -> float | None:
    sims = [c.vector_similarity for c in chunks if c.vector_similarity is not None]
    return max(sims) if sims else None


def fuse(vector_ids: list[str], text_ids: list[str], keyword_weight: float = 1.0) -> dict[str, float]:
    """Reciprocal rank fusion over two ranked id lists; the keyword leg's contribution is multiplied
    by `keyword_weight` (1.0 = equal weight)."""
    scores: dict[str, float] = {}
    for ranked, w in ((vector_ids, 1.0), (text_ids, keyword_weight)):
        for rank, cid in enumerate(ranked, start=1):
            scores[cid] = scores.get(cid, 0.0) + w / (RRF_K + rank)
    return scores


def keyword_ids(cur, question: str, keyword_query: str = "or", collection: str = "measures") -> list[str]:
    """Ranked full-text candidates. "or": any meaningful term. "and_first": all words
    (`websearch_to_tsquery`); if that returns fewer than AND_FIRST_MIN_ROWS rows, the OR query instead."""
    if keyword_query not in ("or", "and_first"):
        raise ValueError(f"unknown keyword_query {keyword_query!r}")
    if keyword_query == "and_first":
        cur.execute(_TEXT_AND_SQL, {"t": question, "n": CANDIDATES, "c": collection})
        rows = [r[0] for r in cur.fetchall()]
        if len(rows) >= AND_FIRST_MIN_ROWS:
            return rows
    cur.execute(_TEXT_SQL, {"t": question, "n": CANDIDATES, "c": collection})
    return [r[0] for r in cur.fetchall()]


def vector_candidates(cur, qvec: str, collection: str = "measures") -> list[tuple[str, float]]:
    cur.execute(_VECTOR_SQL, {"q": qvec, "n": CANDIDATES, "c": collection})
    return [(cid, float(s)) for cid, s in cur.fetchall()]


def search_docs(question: str, k: int = DEFAULT_K, embedder: Embedder | None = None,
                mode: Literal["hybrid", "vector", "keyword"] = DEFAULT_MODE,
                keyword_weight: float = DEFAULT_KEYWORD_WEIGHT,
                keyword_query: Literal["or", "and_first"] = DEFAULT_KEYWORD_QUERY,
                collection: Literal["measures", "coverage"] = "measures") -> list[Chunk]:
    """`mode` is for evaluation ablations. hybrid = RRF of vector and full-text lists;
    vector (default) / keyword rank by that list alone. In keyword mode the returned chunks still get their
    cosine similarity (so the support threshold gates identically); only the ranking differs.
    `keyword_weight` scales the keyword leg in the fusion; `keyword_query` picks how that leg is
    queried (see `keyword_ids`). `collection` picks the document set searched: "measures" (the CMS / HCAHPS
    measure documents, the default and the only set before coverage was added) or "coverage" (Medicare
    National Coverage Determinations); a search never returns chunks of the other set."""
    if mode not in ("hybrid", "vector", "keyword"):
        raise ValueError(f"unknown retrieval mode {mode!r}")
    if collection not in ("measures", "coverage"):
        raise ValueError(f"unknown collection {collection!r}")
    embedder = embedder or OpenAIEmbedder()
    qvec = to_pgvector(embedder.encode([question])[0])
    def _search(cur):
        vec, text_ids = [], []
        if mode != "keyword":
            vec = vector_candidates(cur, qvec, collection)
        if mode != "vector":
            text_ids = keyword_ids(cur, question, keyword_query, collection)
        sims = dict(vec)
        fused = fuse([cid for cid, _ in vec], text_ids, keyword_weight)
        best = sorted(fused, key=fused.get, reverse=True)[:k]
        if not best:
            return [], sims, fused, {}
        if mode == "keyword":
            cur.execute(_SIM_SQL, {"q": qvec, "ids": best, "c": collection})
            sims = {cid: float(s) for cid, s in cur.fetchall()}
        cur.execute(_FETCH_SQL, {"ids": best, "c": collection})
        rows = {r[0]: r for r in cur.fetchall()}
        return best, sims, fused, rows

    best, sims, fused, rows = db.run(os.environ["HQ_SERVICE_URL"], _search)
    if not best:
        return []
    return [Chunk(cid, rows[cid][1], rows[cid][2], rows[cid][3], rows[cid][4], rows[cid][5],
                  sims.get(cid), fused[cid]) for cid in best]
