"""Validate model-written SQL before it touches the database.

The service lets a language model write SQL from a plain-language question. This
module is one of two independent safeguards (the other is the database role, which
can only SELECT from schema `hq`). A query is run only if it is:

  * exactly one statement,
  * a SELECT (CTEs and UNION / INTERSECT / EXCEPT allowed),
  * free of any write, DDL, COPY, SET, locking or SELECT ... INTO clause,
  * reading only allow-listed tables and views in schema `hq`,
  * free of server-side functions that read files, sleep, or change settings.

`check()` returns the normalized SQL with a row limit applied, or raises `UnsafeSQL`
with a reason that is safe to show the user.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

SCHEMA = "hq"
ALLOWED_TABLES = frozenset({
    "hospitals", "measures", "measure_values",
    "v_tx_latest", "v_scorecard", "v_benchmarks", "v_hcahps", "v_tx_vs_national",
})
MAX_ROWS = 200

# Looked up by name so a sqlglot upgrade that renames or drops a class cannot break import.
_FORBIDDEN_NODES = tuple(
    c for c in (getattr(exp, n, None) for n in (
        "Insert", "Update", "Delete", "Merge", "Drop", "Create", "Alter", "AlterTable",
        "TruncateTable", "Copy", "Command", "Set", "Grant", "Transaction", "Commit",
        "Rollback", "Use", "Pragma", "Into", "Lock",
    )) if c is not None)
_FORBIDDEN_FUNCTIONS = frozenset({
    "dblink", "dblink_exec", "lo_import", "lo_export", "set_config", "current_setting",
    "query_to_xml", "copy",
})
_SET_OPERATION = getattr(exp, "SetOperation", exp.Union)


class UnsafeSQL(ValueError):
    """Raised when a query must not be run."""


def check(sql: str, max_rows: int = MAX_ROWS) -> str:
    try:
        statements = [s for s in sqlglot.parse(sql or "", read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeSQL("could not parse the query") from e
    if len(statements) != 1:
        raise UnsafeSQL("exactly one statement is allowed")
    tree = statements[0]
    if not isinstance(tree, (exp.Select, _SET_OPERATION)):
        raise UnsafeSQL("only SELECT queries are allowed")

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeSQL(f"{type(node).__name__.upper()} is not allowed")
        if isinstance(node, exp.Select) and (node.args.get("into") or node.args.get("locks")):
            raise UnsafeSQL("SELECT ... INTO and row locks are not allowed")
        if isinstance(node, exp.Func):
            name = (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()
            if name.startswith("pg_") or name in _FORBIDDEN_FUNCTIONS:
                raise UnsafeSQL(f"function {name} is not allowed")

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        name, schema = t.name.lower(), (t.db or "").lower()
        if t.catalog:
            raise UnsafeSQL("cross-database references are not allowed")
        if not schema and name in cte_names:
            continue
        if schema not in ("", SCHEMA) or name not in ALLOWED_TABLES:
            raise UnsafeSQL(f"table {t.sql(dialect='postgres')} is not available")

    limit = tree.args.get("limit")
    current = None
    if limit is not None and isinstance(limit.expression, exp.Literal) and limit.expression.is_int:
        current = int(limit.expression.this)
    if current is None or current > max_rows:
        tree = tree.limit(max_rows)
    return tree.sql(dialect="postgres")
