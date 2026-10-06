import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.sql_guard import MAX_ROWS, UnsafeSQL, check  # noqa: E402

ALLOWED = [
    "SELECT name, city FROM hq.hospitals WHERE state = 'TX'",
    "SELECT h.name, v.score FROM hq.hospitals h JOIN hq.measure_values v ON v.facility_id = h.facility_id",
    "WITH tx AS (SELECT * FROM hq.hospitals WHERE state = 'TX') SELECT county, COUNT(*) FROM tx GROUP BY county",
    "SELECT name FROM hospitals UNION SELECT name FROM measures",
    "SELECT name, RANK() OVER (PARTITION BY county ORDER BY rating DESC) FROM hq.hospitals",
    "select * from hq.v_scorecard -- trailing comment",
]

REJECTED = [
    ("", "empty"),
    ("INSERT INTO hq.hospitals (name) VALUES ('x')", "write"),
    ("UPDATE hq.hospitals SET name = 'x'", "write"),
    ("DELETE FROM hq.hospitals", "write"),
    ("DROP TABLE hq.hospitals", "ddl"),
    ("SELECT 1; DROP TABLE hq.hospitals", "two statements"),
    ("SELECT * FROM hq.hospitals; SELECT * FROM hq.measures", "two statements"),
    ("WITH d AS (DELETE FROM hq.hospitals RETURNING *) SELECT * FROM d", "write inside a CTE"),
    ("SELECT * FROM pg_catalog.pg_user", "system catalog"),
    ("SELECT * FROM information_schema.tables", "information schema"),
    ("SELECT * FROM auth.users", "other schema"),
    ("SELECT * FROM public.hospitals", "other schema, allowed name"),
    ("SELECT * FROM hq.secrets", "unknown table"),
    ("SELECT * FROM otherdb.hq.hospitals", "cross-database"),
    ("SELECT pg_sleep(10)", "sleep"),
    ("SELECT pg_read_file('/etc/passwd')", "file read"),
    ("SELECT set_config('statement_timeout', '0', false)", "settings"),
    ("SELECT * INTO hq.copy FROM hq.hospitals", "select into"),
    ("SELECT * FROM hq.hospitals FOR UPDATE", "row lock"),
    ("COPY hq.hospitals TO '/tmp/x'", "copy"),
    ("SET statement_timeout = 0", "set"),
    ("this is not sql at all (", "garbage"),
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql):
    out = check(sql)
    assert out.upper().startswith(("SELECT", "WITH"))
    assert f"LIMIT {MAX_ROWS}" in out


@pytest.mark.parametrize("sql,why", REJECTED)
def test_rejected(sql, why):
    with pytest.raises(UnsafeSQL):
        check(sql)


def test_small_limit_kept():
    assert "LIMIT 5" in check("SELECT name FROM hq.hospitals LIMIT 5")


def test_large_limit_clamped():
    out = check("SELECT name FROM hq.hospitals LIMIT 100000")
    assert f"LIMIT {MAX_ROWS}" in out and "100000" not in out


def test_cte_named_like_a_forbidden_table_does_not_open_it():
    with pytest.raises(UnsafeSQL):
        check("WITH x AS (SELECT 1) SELECT * FROM auth.users")
