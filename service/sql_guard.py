"""Validate model-written SQL before it touches the database.

The service lets a language model write SQL from a plain-language question. This
module is one of two independent safeguards (the other is the database role, which
can only SELECT from schema `hq`). A query is run only if it is:

  * exactly one statement,
  * a SELECT (CTEs and UNION / INTERSECT / EXCEPT allowed; recursive CTEs are not),
  * free of any write, DDL, COPY, SET, locking or SELECT ... INTO clause,
  * reading only allow-listed tables and views in schema `hq`. An unqualified name is
    accepted only if it is one of those allow-listed names (the reader login's search_path is
    `hq`) or a CTE visible in that very scope (a CTE defined in a sibling subquery does not
    count, so it cannot hide a system catalog). No CTE may be named like an allowed table,
  * calling only functions on an allow-list (analytics: aggregates, window functions, math,
    string and date-part functions, casts to plain types). Everything else, including every
    session / server information function, is rejected by default.

`check()` returns the normalized SQL with a row limit applied, or raises `UnsafeSQL`
with a reason that is safe to show the user.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

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
_SET_OPERATION = getattr(exp, "SetOperation", exp.Union)

# Function allow-list, by sqlglot node class name (sqlglot maps many Postgres names onto one class,
# e.g. CEIL/CEILING -> Ceil, BTRIM/LTRIM/RTRIM -> Trim). A function sqlglot cannot type (`Anonymous`)
# is never allowed: every function the evaluation corpus uses is typed. The first group is what the
# corpus in tests/sql_corpus.py uses; the rest are ordinary analytics functions. See
# tests/test_sql_guard.py (test_corpus_replay). Deliberately absent: current_* / session / server
# information, pg_*, version, inet_*, txid_*, to_reg*, has_*_privilege, set_config / current_setting,
# repeat, lpad / rpad, generate_series, unnest, random, large-object, xml / json export, dblink, sleep,
# file, lock, notify.
ALLOWED_FUNCTIONS = frozenset({
    # corpus
    "And", "Or", "Avg", "Case", "If", "Cast", "Coalesce", "Count", "Left", "Lag", "LogicalOr", "Max", "Min",
    "Nullif", "PercentRank", "PercentileCont", "Rank", "Round", "RowNumber", "Stddev", "StddevPop", "Sum",
    "Trim", "Upper",
    # more aggregates and ordered-set / statistical aggregates
    "StddevSamp", "Variance", "VariancePop", "LogicalAnd", "ArrayAgg", "GroupConcat", "PercentileDisc",
    "Corr", "CovarPop", "CovarSamp", "RegrSlope", "RegrIntercept", "RegrR2", "RegrCount", "RegrAvgx",
    "RegrAvgy", "RegrSxx", "RegrSyy", "RegrSxy",
    # window functions
    "DenseRank", "CumeDist", "Ntile", "Lead", "FirstValue", "LastValue", "NthValue",
    # math and null handling
    "Abs", "Ceil", "Floor", "Sqrt", "Ln", "Log", "Exp", "Pow", "Sign", "Trunc", "Greatest", "Least", "Exists",
    # strings
    "Lower", "Initcap", "Substring", "Right", "Length", "Concat", "ConcatWs", "Replace", "SplitPart",
    "StrPosition",
    # date parts
    "Extract", "TimestampTrunc",
})
_ALLOWED_CAST_TYPES = frozenset(
    t for t in (getattr(exp.DataType.Type, n, None) for n in (
        "TINYINT", "SMALLINT", "INT", "BIGINT", "DECIMAL", "FLOAT", "DOUBLE", "REAL",
        "TEXT", "VARCHAR", "CHAR", "BOOLEAN", "DATE", "TIMESTAMP", "TIMESTAMPTZ")) if t is not None)
# Keywords Postgres reads as values that sqlglot may leave as a bare column name.
_SESSION_KEYWORDS = frozenset({"user", "current_user", "session_user", "current_role", "system_user",
                               "current_catalog", "current_schema", "localtime", "localtimestamp"})


class UnsafeSQL(ValueError):
    """Raised when a query must not be run."""


def _function_name(node: exp.Func) -> str:
    return node.name.lower() if isinstance(node, exp.Anonymous) else node.sql_name().lower()


def _check_nodes(tree) -> None:
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise UnsafeSQL(f"{type(node).__name__.upper()} is not allowed")
        if isinstance(node, exp.Select) and (node.args.get("into") or node.args.get("locks")):
            raise UnsafeSQL("SELECT ... INTO and row locks are not allowed")
        if isinstance(node, exp.With) and node.args.get("recursive"):
            raise UnsafeSQL("recursive queries are not allowed")
        if isinstance(node, exp.Func) and (isinstance(node, exp.Anonymous) or type(node).__name__ not in ALLOWED_FUNCTIONS):
            raise UnsafeSQL(f"function {_function_name(node)} is not allowed")
        if isinstance(node, exp.Cast) and node.to.this not in _ALLOWED_CAST_TYPES:
            raise UnsafeSQL("casting to that type is not allowed")
        if isinstance(node, exp.Column) and not node.table and node.name.lower() in _SESSION_KEYWORDS:
            raise UnsafeSQL(f"{node.name.lower()} is not allowed")
        if isinstance(node, exp.CTE):
            name = node.alias_or_name.lower()
            if name in ALLOWED_TABLES or name.startswith("pg_"):
                raise UnsafeSQL(f"a CTE may not be named {name}")


def _check_table(t: exp.Table, visible_ctes: set[str]) -> None:
    if not isinstance(t.this, exp.Identifier):
        raise UnsafeSQL("table functions are not allowed")
    name, schema = t.name.lower(), (t.db or "").lower()
    if t.catalog:
        raise UnsafeSQL("cross-database references are not allowed")
    if not schema:
        # The reader login's search_path is `hq`, so an unqualified allow-listed name is the hq table (no CTE
        # may carry such a name, see _check_nodes). The evaluation's reference queries are written this way.
        if name in visible_ctes or name in ALLOWED_TABLES:
            return
        raise UnsafeSQL(f"table {t.sql(dialect='postgres')} is not available")
    if schema != SCHEMA or name not in ALLOWED_TABLES:
        raise UnsafeSQL(f"table {t.sql(dialect='postgres')} is not available")


def _check_tables(tree) -> None:
    """Every table reference is `hq.<allowed name>` or an unqualified CTE visible in its own scope."""
    try:
        scopes = traverse_scope(tree)
    except Exception as e:  # noqa: BLE001  (sqlglot raises several types on odd input)
        raise UnsafeSQL("could not analyse the query") from e
    seen: set[int] = set()
    for scope in scopes:
        visible = {name.lower() for name in scope.cte_sources}
        for t in scope.tables:
            seen.add(id(t))
            _check_table(t, visible)
    for t in tree.find_all(exp.Table):  # a table the scope walk did not reach is not vouched for
        if id(t) not in seen:
            _check_table(t, set())


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

    _check_nodes(tree)
    _check_tables(tree)

    limit = tree.args.get("limit")
    current = None
    if limit is not None and isinstance(limit.expression, exp.Literal) and limit.expression.is_int:
        current = int(limit.expression.this)
    if current is None or current > max_rows:
        tree = tree.limit(max_rows)
    return tree.sql(dialect="postgres")
