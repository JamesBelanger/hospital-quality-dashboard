"""Retrieval-only study on the 22 `definition` questions (embedding calls only; no chat model).

    python -m evals.retrieval_study [--runs-queries evals/results/run_X.json] [--tag NAME]

For each configuration, the ranked list is built with the same functions `search_docs` uses
(`vector_candidates`, `keyword_ids`, `fuse`), so the study measures the production code path. The query
embedding and the two candidate lists are fetched once per query and re-fused offline per configuration.

Metrics: hit@k = any of `expected_chunk_ids` in the top k (k = 3, 6, 8, 10); MRR = mean of 1/rank of the first
expected chunk in the top 10 (0 when absent).

The 22 definition questions are a DEVELOPMENT set for retrieval (retrieval was already adjusted after
looking at them). Choice of configuration follows a rule fixed in advance (see `select`).

Writes evals/results/retrieval_study_<UTC date>[_<tag>].md and .json.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import psycopg  # noqa: E402

from service import retrieval  # noqa: E402
from service.embedder import OpenAIEmbedder, to_pgvector  # noqa: E402

QUESTIONS = ROOT / "evals" / "questions_v1.jsonl"
RESULTS = ROOT / "evals" / "results"
KS = (3, 6, 8, 10)

# name -> (mode, keyword_query, keyword_weight)
CONFIGS = {
    "vector": ("vector", "or", 1.0),
    "hybrid_or": ("hybrid", "or", 1.0),
    "hybrid_or_w0.5": ("hybrid", "or", 0.5),
    "hybrid_or_w0.25": ("hybrid", "or", 0.25),
    "hybrid_and_first": ("hybrid", "and_first", 1.0),
    "hybrid_and_first_w0.5": ("hybrid", "and_first", 0.5),
}
# Tie-break order for the selection rule: simpler first.
SIMPLICITY = ["vector", "hybrid_and_first", "hybrid_or_w0.25", "hybrid_or_w0.5", "hybrid_and_first_w0.5", "hybrid_or"]


def rank_list(vec, text_ids, mode, keyword_weight) -> list[str]:
    fused = retrieval.fuse([c for c, _ in vec], [] if mode == "vector" else text_ids, keyword_weight)
    return sorted(fused, key=fused.get, reverse=True)  # identical to search_docs


def score(ranked: dict[str, list[str]], qs: list[dict]) -> dict:
    """ranked: question id -> ranked chunk ids. Returns hits per k and MRR."""
    out = {f"hit@{k}": 0 for k in KS}
    rr = 0.0
    per_q = {}
    for q in qs:
        exp = set(q["expected_chunk_ids"])
        lst = ranked[q["id"]][:10]
        pos = next((i for i, c in enumerate(lst, 1) if c in exp), None)
        per_q[q["id"]] = pos
        for k in KS:
            out[f"hit@{k}"] += int(pos is not None and pos <= k)
        rr += 1.0 / pos if pos else 0.0
    out["mrr"] = rr / len(qs)
    out["n"] = len(qs)
    out["first_rank"] = per_q
    return out


def select(table: dict[str, dict]) -> tuple[str, int, str]:
    """Rule fixed in advance: best hit@6; ties -> higher MRR; ties -> simpler (SIMPLICITY order).
    k stays 6 unless hit@8 exceeds hit@6 by 2+ questions, then 8."""
    best = sorted(table, key=lambda n: (-table[n]["hit@6"], -round(table[n]["mrr"], 12), SIMPLICITY.index(n)))[0]
    k = 8 if table[best]["hit@8"] - table[best]["hit@6"] >= 2 else 6
    return best, k, f"hit@6={table[best]['hit@6']}, mrr={table[best]['mrr']:.3f}, hit@8-hit@6={table[best]['hit@8'] - table[best]['hit@6']}"


def run_queries(queries: dict[str, str], qs: list[dict]) -> tuple[dict, dict]:
    emb = OpenAIEmbedder()
    ids = [q["id"] for q in qs]
    vecs = emb.encode([queries[i] for i in ids])
    table_ranked = {name: {} for name in CONFIGS}
    with psycopg.connect(os.environ["HQ_SERVICE_URL"], autocommit=True, connect_timeout=20) as conn:
        cur = conn.cursor()
        for i, v in zip(ids, vecs):
            qtext = queries[i]
            vec = retrieval.vector_candidates(cur, to_pgvector(v))
            kw = {kq: retrieval.keyword_ids(cur, qtext, kq) for kq in ("or", "and_first")}
            for name, (mode, kq, w) in CONFIGS.items():
                table_ranked[name][i] = rank_list(vec, kw[kq], mode, w)
    table = {name: score(table_ranked[name], qs) for name in CONFIGS}
    return table, {"embed_tokens": emb.tokens_used, "embed_cost_usd": emb.cost_usd}


def fmt(table: dict) -> list[str]:
    n = next(iter(table.values()))["n"]
    lines = ["| configuration | hit@3 | hit@6 | hit@8 | hit@10 | MRR |", "|---|---|---|---|---|---|"]
    for name, r in table.items():
        lines.append(f"| {name} | " + " | ".join(f"{r[f'hit@{k}']}/{n}" for k in KS) + f" | {r['mrr']:.3f} |")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-queries", default=None,
                    help="saved eval run JSON whose records hold answer.doc_query; also report the table on those")
    ap.add_argument("--tag", default="")
    args = ap.parse_args(argv)
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    qs = [q for q in map(json.loads, QUESTIONS.read_text(encoding="utf-8").splitlines())
          if q["type"] == "definition"]
    assert len(qs) == 22, len(qs)
    t_plain, cost1 = run_queries({q["id"]: q["question"] for q in qs}, qs)
    best, k, why = select(t_plain)
    result = dict(date=datetime.datetime.now(datetime.timezone.utc).date().isoformat(), n=len(qs),
                  question_text=dict(table=t_plain, selected=best, k=k, why=why), embed_cost_usd=cost1["embed_cost_usd"])

    md = [f"# Retrieval study ({result['date']})", "",
          "22 `definition` questions (development set for retrieval). Query = question text.", ""]
    md += fmt(t_plain)
    md += ["", f"Selected by the fixed rule: **{best}**, k = **{k}** ({why}).", ""]

    if args.runs_queries:
        run = json.loads(Path(args.runs_queries).read_text(encoding="utf-8"))
        dq = {r["id"]: (r.get("answer") or {}).get("doc_query") for r in run["records"] if r["type"] == "definition"}
        have = {q["id"]: dq[q["id"]] for q in qs if dq.get(q["id"])}
        sub = [q for q in qs if q["id"] in have]
        if sub:
            t_pl, cost2 = run_queries(have, sub)
            b2, k2, why2 = select(t_pl)
            result["planner_queries"] = dict(source=Path(args.runs_queries).name, n=len(sub), table=t_pl, selected=b2,
                                             k=k2, why=why2, embed_cost_usd=cost2["embed_cost_usd"],
                                             queries=have)
            md += [f"## Planner-rewritten queries (`doc_query` from {Path(args.runs_queries).name}; "
                   f"{len(sub)} of {len(qs)} questions had one)", ""]
            md += fmt(t_pl)
            md += ["", f"Same rule on these queries would pick: {b2}, k = {k2} ({why2}). Informational only; "
                      "the configuration was frozen from the question-text table.", ""]
        else:
            md += ["Planner queries: the saved run holds no `doc_query` per question.", ""]
    md += ["First-expected-chunk rank per question (None = not in top 10):", "", "| id | " + " | ".join(CONFIGS) + " |",
           "|---|" + "---|" * len(CONFIGS)]
    for q in qs:
        md.append(f"| {q['id']} | " + " | ".join(str(t_plain[c]["first_rank"][q["id"]]) for c in CONFIGS) + " |")

    stamp = result["date"] + (f"_{args.tag}" if args.tag else "")
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"retrieval_study_{stamp}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (RESULTS / f"retrieval_study_{stamp}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
