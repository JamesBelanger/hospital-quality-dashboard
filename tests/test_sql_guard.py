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


# ---- abuse cases from the red-team pass (redteam/part_a_results.json): each was ACCEPTED by the first validator ----
SHADOWING = [  # a CTE defined in one scope used to hide the real catalog / log table used in another
    "select * from pg_roles, (with pg_roles as (select 1) select 1) s",
    "with pg_roles as (select 1) select * from pg_roles",
    "select * from pg_user where exists (with pg_user as (select 1) select 1 from pg_user)",
    "select * from pg_settings, (with pg_settings as (select 1) select 1) s",
    "select * from pg_stat_activity, (with pg_stat_activity as (select 1) select 1) s",
    "select (with pg_roles as (select 1) select 1), rolname from pg_roles",
    "select * from pg_authid, (with pg_authid as (select 1) select 1) s",
    "select * from pg_shadow, (with pg_shadow as (select 1) select 1) s",
    "select * from pg_class, (with pg_class as (select 1) select 1) s",
    "select * from hq.hospitals, (with request_log as (select 1) select 1) s, request_log",
    "select * from hq.hospitals, (with chunks as (select 1) select 1) s, chunks",
    "with recursive hospitals as (select * from hospitals) select * from hospitals",  # CTE named like an allowed table
    "with hospitals as (select 1) select * from hq.hospitals",
    "with a as (select * from a) select * from a",  # a non-recursive CTE cannot see itself: `a` is a real table name
    "select * from hq.hospitals where facility_id in (select x from c) and 1 = (with c as (select 1 x) select 1)",
    "select * from request_log",
    "select * from pg_roles",
]
INFORMATION_FUNCTIONS = [
    "select current_user, session_user, current_database(), version(), current_schema()",
    "select inet_server_addr(), inet_server_port(), current_catalog",
    "select txid_current()",
    "select to_regclass('hq_app.request_log')",
    "select has_table_privilege('hq_app.request_log','select')",
    "select current_query()",
    "select user",
    "select 1 from hq.hospitals where facility_id::text = (select current_user)",
    "select facility_name::text::regclass from hq.hospitals",
    "select 'hq_app.request_log'::regclass",
    "select facility_id from hq.hospitals where facility_id::regclass is null",
    "select hq.version()",
    "select pg_catalog.current_setting('x')",
    "select now()", "select random()",
]
BLOW_UPS_AND_SIBLINGS = [
    "select repeat('x', 100000000)", "select repeat('x', 2000000000)",
    "select md5(repeat('a', 500000000))", "select lpad('x', 1000000000, 'y')", "select rpad('x', 1000000000, 'y')",
    "select 'x' || repeat('y',1000000000)",
    "select generate_series(1,1000000000)",
    "select count(*) from (select generate_series(1,1000000000)) s",
    "select * from generate_series(1,1000000000)",
    "select * from hq.hospitals where facility_id in (select unnest(array(select generate_series(1,100000000))))",
    "select string_agg(repeat('x',1000), ',') from (select generate_series(1,1000000)) s",
    "select * from hq.hospitals, unnest(array[1,2]) u",
    "select unnest(array[1,2,3])",
    "with recursive r(n) as (select 1 union all select n+1 from r) select count(*) from r",
    "with recursive r(n) as (select 1 union all select n+1 from r) select n from r limit 100",
    "with recursive x as (select 1 union all select 1 from x) select * from x limit 1",
    "select lo_get(16384)", "select lo_from_bytea(0, 'abc')", "select lo_unlink(1)", "select loread(1,1)",
    "select lowrite(1,'a')", "select dblink_connect('host=x')",
    "select table_to_xml('hq_app.request_log', true, false, '')", "select schema_to_xml('hq_app', true, false, '')",
    "select database_to_xml(true, false, '')", "select query_to_xml_and_xmlschema('select 1', true, false, '')",
    "select cursor_to_xml('c', 1, true, false, '')", "select xmlelement(name x, 'a')",
    "select ts_debug('english','a')", "select row_to_json(h) from hq.hospitals h",
    "select to_json(h) from hq.hospitals h", "select pg_ls_dir('.')",
]


@pytest.mark.parametrize("sql", SHADOWING + INFORMATION_FUNCTIONS + BLOW_UPS_AND_SIBLINGS)
def test_abuse_cases_rejected(sql):
    with pytest.raises(UnsafeSQL):
        check(sql)


def test_abuse_case_count():
    assert len(SHADOWING) + len(INFORMATION_FUNCTIONS) + len(BLOW_UPS_AND_SIBLINGS) >= 60


@pytest.mark.parametrize("sql", [
    "with tx as (select * from hq.hospitals where state = 'TX') select * from tx where facility_id in (select facility_id from tx)",
    "with a as (select 1 x), b as (select x from a) select * from b union all select x from a",
    "select * from hq.hospitals where facility_id in (with c as (select facility_id from hq.measure_values) select facility_id from c)",
    "select * from hospitals h join measure_values v on v.facility_id = h.facility_id",  # unqualified allow-listed name: search_path is hq
    "select count(*) filter (where overall_rating = 5), round(avg(overall_rating)::numeric, 2), "
    "percentile_cont(0.5) within group (order by overall_rating) from hq.hospitals",
    "select extract(year from period_end), date_trunc('month', period_end) from hq.measure_values",
    "select upper(state), left(facility_name, 3), coalesce(county, 'x'), nullif(state, 'TX') from hq.hospitals",
    "select state, string_agg(facility_name, ', ') from hq.hospitals group by state",
    "select facility_id, lag(score) over (partition by measure_id order by period_end), ntile(4) over () from hq.measure_values",
    "select score::int, score::text, period_end::date from hq.measure_values",
])
def test_ordinary_analytics_still_accepted(sql):
    assert "LIMIT" in check(sql)


# ---- row limits and comments: must be clamped / stay harmless ----
@pytest.mark.parametrize("sql", [
    "select facility_id from hq.hospitals limit all", "select facility_id from hq.hospitals limit 1000000 offset 0",
    "select facility_id from hq.hospitals limit null", "select facility_id from hq.hospitals fetch first 100000 rows only",
    "select facility_id from hq.hospitals offset 5 rows fetch first 5000 rows only",
    "select facility_id from hq.hospitals limit 10 + 100000", "select facility_id from hq.hospitals limit (select 100000)",
    "select facility_id from hq.hospitals limit 1e6", "select facility_id from hq.hospitals limit 0x10",
    "select facility_id from hq.hospitals limit -1", "select facility_id from hq.hospitals limit 201",
    "(select facility_id from hq.hospitals limit 5) union all (select facility_id from hq.hospitals limit 5000)",
    "select facility_id from hq.hospitals union all select facility_id from hq.hospitals limit 99999",
    "select facility_id from hq.hospitals",
])
def test_row_limit_is_clamped_to_max(sql):
    import re
    out = check(sql)
    final = re.findall(r"LIMIT (\d+)", out)[-1]
    assert int(final) <= MAX_ROWS


@pytest.mark.parametrize("sql", [
    "select facility_name from hq.hospitals /* ; drop table x */",
    "select facility_name from hq.hospitals; ",
    "select facility_name from hq.hospitals where 1=1 --'; drop table hq.hospitals",
    "select $$;drop table hq.hospitals;$$ from hq.hospitals",
])
def test_comments_and_quotes_hide_nothing(sql):
    import sqlglot
    out = check(sql)
    parsed = [t for t in sqlglot.parse(out, read="postgres") if t is not None]
    assert len(parsed) == 1 and type(parsed[0]).__name__ == "Select"  # the text after the comment / quote is data, not a statement


# ---- corpus replay: nothing the old validator accepted is lost, except under a named rule ----
def test_corpus_replay():
    from tests import sql_corpus as C

    truth, (files, _views) = C.truth_sql(), C.sql_files()
    assert len(truth) >= 50 and len(files) >= 20
    for label, sql in truth + files:
        check(sql)  # every reference query and every project analysis query is still accepted
    gen = C.generated_sql()
    assert len(gen) >= 90
    n_reject = 0
    for label, sql, expect in gen:
        if expect == "accept":
            check(sql)
        else:  # the only legitimate-looking one is a CTE named like an allowed table (rule F1); the rest are attacks
            n_reject += 1
            with pytest.raises(UnsafeSQL):
                check(sql)
    assert n_reject == 4


def test_allow_list_has_no_session_or_server_functions():
    from service.sql_guard import ALLOWED_FUNCTIONS
    bad = {"CurrentUser", "SessionUser", "CurrentDatabase", "CurrentSchema", "CurrentSchemas", "CurrentVersion",
           "CurrentCatalog", "Repeat", "Pad", "ExplodingGenerateSeries", "GenerateSeries", "Explode", "Unnest",
           "Rand", "CurrentTimestamp", "CurrentDate", "Anonymous", "Array"}
    assert not (ALLOWED_FUNCTIONS & bad)
