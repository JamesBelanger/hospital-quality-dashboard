"""Embed docs_index/chunks.jsonl (collection "measures") and docs_index/chunks_ncd.jsonl (collection "coverage")
and load them into Postgres (pgvector) as hq_docs.chunks.

Re-runnable: a chunk is re-embedded only when its text or the embedding model changed,
so a second run after a small edit costs almost nothing. Chunks that no longer exist
are deleted. Each row also gets a full-text column for keyword search, so retrieval
can combine vector and keyword matches.

Run as the database owner (DATABASE_URL in .env). Needs OPENAI_API_KEY.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from service.embedder import OpenAIEmbedder, to_pgvector  # noqa: E402

# (file, collection): the collection is stored per row so retrieval can search one document set at a time
SOURCES = [(REPO / "docs_index" / "chunks.jsonl", "measures"), (REPO / "docs_index" / "chunks_ncd.jsonl", "coverage")]

DDL = """
create schema if not exists hq_docs;
create table if not exists hq_docs.chunks (
    chunk_id      text primary key,
    doc_id        text not null,
    doc_title     text not null,
    source_url    text not null,
    section_title text not null,
    page_start    int,
    page_end      int,
    body          text not null,
    measure_ids   text[] not null default '{{}}',
    text_sha      text not null,
    embed_model   text not null,
    embedding     extensions.vector({dims}) not null,
    tsv           tsvector generated always as (to_tsvector('english', section_title || ' ' || body)) stored,
    collection    text not null default 'measures'
);
alter table hq_docs.chunks add column if not exists collection text not null default 'measures';
create index if not exists chunks_collection_idx on hq_docs.chunks (collection);
create index if not exists chunks_embedding_hnsw on hq_docs.chunks using hnsw (embedding extensions.vector_cosine_ops);
create index if not exists chunks_tsv_gin on hq_docs.chunks using gin (tsv);
create index if not exists chunks_measure_ids_gin on hq_docs.chunks using gin (measure_ids);
"""


def main():
    load_dotenv(REPO / ".env")
    chunks = []
    for path, collection in SOURCES:
        if not path.exists():
            raise SystemExit(f"{path.name} is missing: run docs_index/chunk.py / chunk_ncd.py first")
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                chunks.append(dict(json.loads(line), collection=collection))
    for c in chunks:
        c["text_sha"] = hashlib.sha256(c["text"].encode("utf-8")).hexdigest()
    embedder = OpenAIEmbedder()

    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=20) as conn:
        cur = conn.cursor()
        cur.execute(DDL.format(dims=embedder.dims))
        cur.execute("select chunk_id, text_sha, embed_model from hq_docs.chunks")
        have = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
        cur.execute("select chunk_id, collection from hq_docs.chunks")
        have_coll = dict(cur.fetchall())

        # re-embed when the text, the model or the collection changed (existing rows default to "measures": unchanged)
        todo = [c for c in chunks if have.get(c["chunk_id"]) != (c["text_sha"], embedder.model)
                or have_coll.get(c["chunk_id"]) != c["collection"]]
        gone = sorted(set(have) - {c["chunk_id"] for c in chunks})
        vectors = embedder.encode([f'{c["section_title"]}\n{c["text"]}' for c in todo]) if todo else []

        if gone:
            cur.execute("delete from hq_docs.chunks where chunk_id = any(%s)", (gone,))
        cur.executemany(
            """insert into hq_docs.chunks (chunk_id, doc_id, doc_title, source_url, section_title, page_start,
                                           page_end, body, measure_ids, text_sha, embed_model, embedding, collection)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::extensions.vector, %s)
               on conflict (chunk_id) do update set
                   doc_id = excluded.doc_id, doc_title = excluded.doc_title, source_url = excluded.source_url,
                   section_title = excluded.section_title, page_start = excluded.page_start,
                   page_end = excluded.page_end, body = excluded.body, measure_ids = excluded.measure_ids,
                   text_sha = excluded.text_sha, embed_model = excluded.embed_model, embedding = excluded.embedding,
                   collection = excluded.collection""",
            [(c["chunk_id"], c["doc_id"], c["doc_title"], c["source_url"], c["section_title"], c["page_start"],
              c["page_end"], c["text"], c["measure_ids"], c["text_sha"], embedder.model, to_pgvector(v),
              c["collection"])
             for c, v in zip(todo, vectors)])
        conn.commit()
        cur.execute("select collection, count(*), count(distinct doc_id) from hq_docs.chunks group by collection order by 1")
        per = cur.fetchall()

    print(f"embedded {len(todo)} chunks ({embedder.tokens_used:,} tokens, ${embedder.cost_usd:.4f}), "
          f"deleted {len(gone)}, unchanged {len(chunks) - len(todo)}")
    print("hq_docs.chunks: " + "; ".join(f"{c}: {n} rows from {d} documents" for c, n, d in per)
          + f"; model {embedder.model} ({embedder.dims} dims)")


if __name__ == "__main__":
    main()
