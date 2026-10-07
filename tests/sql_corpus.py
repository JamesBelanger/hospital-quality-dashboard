"""The SQL corpus the validator's function allow-list was built from and is replayed against.

  truth   every `truth_sql` in evals/questions_*.jsonl (hand-checked reference queries)
  files   SELECT statements in sql/*.sql and sql/daily/*.sql (the project's own analysis queries)
  views   the same files' non-SELECT statements (view definitions): used for the function survey only
  gen     SQL the service itself generated, kept in tests/fixtures/generated_sql_corpus.json
          (from evals/results/parity_12_*.json and the red-team result files; the eval run files
          do not store SQL)
"""
from __future__ import annotations

import json
from pathlib import Path

import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parents[1]
GEN_PATH = ROOT / "tests" / "fixtures" / "generated_sql_corpus.json"


def truth_sql() -> list[tuple[str, str]]:
    out = []
    for f in sorted((ROOT / "evals").glob("questions_*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                q = json.loads(line)
                if q.get("truth_sql"):
                    out.append((f"truth:{q['id']}", q["truth_sql"]))
    return out


def sql_files() -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """(SELECT statements, other statements) from sql/*.sql and sql/daily/*.sql."""
    selects, others = [], []
    for f in sorted(list((ROOT / "sql").glob("*.sql")) + list((ROOT / "sql" / "daily").glob("*.sql"))):
        try:
            stmts = [s for s in sqlglot.parse(f.read_text(encoding="utf-8"), read="postgres") if s is not None]
        except sqlglot.errors.ParseError:
            continue
        for i, s in enumerate(stmts):
            label = f"file:{f.parent.name}/{f.name}#{i}"
            (selects if isinstance(s, (exp.Select, exp.Union)) else others).append((label, s.sql(dialect="postgres")))
    return selects, others


def generated_sql() -> list[tuple[str, str, str]]:
    """(label, sql, expected verdict of the CURRENT validator: "accept" or "reject")."""
    items = json.loads(GEN_PATH.read_text(encoding="utf-8"))
    return [(f"gen:{it['src']}", it["sql"], it["expect"]) for it in items]
