"""Live checks that the hq_reader login can read hospital data and nothing more.

Skipped when HQ_READER_URL is not set (for example in CI without database secrets).
"""
import os
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
URL = os.environ.get("HQ_READER_URL")
pytestmark = pytest.mark.skipif(not URL, reason="HQ_READER_URL not set")


@pytest.fixture()
def cur():
    with psycopg.connect(URL, autocommit=True, connect_timeout=20) as conn:
        yield conn.cursor()


def test_can_read_hospital_data(cur):
    cur.execute("select count(*) from hq.hospitals")
    assert cur.fetchone()[0] > 5000


def test_unqualified_names_resolve_to_hq(cur):
    cur.execute("select count(*) from measures")
    assert cur.fetchone()[0] > 100


@pytest.mark.parametrize("stmt", [
    "insert into hq.hospitals (facility_id) values ('x')",
    "update hq.hospitals set state = 'ZZ'",
    "delete from hq.measure_values",
    "create table hq.t (a int)",
    "drop table hq.hospitals",
])
def test_cannot_write(cur, stmt):
    with pytest.raises(psycopg.Error):
        cur.execute(stmt)


def test_cannot_read_other_schemas(cur):
    with pytest.raises(psycopg.Error):
        cur.execute("select count(*) from auth.users")


def test_long_queries_are_cancelled(cur):
    with pytest.raises(psycopg.errors.QueryCanceled):
        cur.execute("select pg_sleep(8)")


# ---- hq_service: documentation retrieval login (SELECT on hq_docs.chunks only) ----
SERVICE_URL = os.environ.get("HQ_SERVICE_URL")
needs_service = pytest.mark.skipif(not SERVICE_URL, reason="HQ_SERVICE_URL not set")


@pytest.fixture()
def svc():
    with psycopg.connect(SERVICE_URL, autocommit=True, connect_timeout=20) as conn:
        yield conn.cursor()


@needs_service
def test_service_can_read_chunks(svc):
    svc.execute("select count(*) from chunks")  # search_path = hq_docs, extensions
    assert svc.fetchone()[0] > 100


@needs_service
def test_service_can_use_vector_operators(svc):
    svc.execute("select embedding <=> embedding from chunks limit 1")
    assert svc.fetchone()[0] is not None


@needs_service
def test_service_cannot_read_hospital_data(svc):
    with pytest.raises(psycopg.Error):
        svc.execute("select count(*) from hq.hospitals")


@needs_service
@pytest.mark.parametrize("stmt", [
    "delete from hq_docs.chunks",
    "update hq_docs.chunks set body = 'x'",
    "create table hq_docs.t (a int)",
])
def test_service_cannot_write(svc, stmt):
    with pytest.raises(psycopg.Error):
        svc.execute(stmt)


# ---- hq_logger: request log only (INSERT + SELECT on hq_app.request_log) ----
LOG_URL = os.environ.get("HQ_LOG_URL")
OWNER_URL = os.environ.get("DATABASE_URL")
needs_log = pytest.mark.skipif(not LOG_URL, reason="HQ_LOG_URL not set")


@pytest.fixture()
def logger():
    with psycopg.connect(LOG_URL, autocommit=True, connect_timeout=20) as conn:
        yield conn.cursor()
    if OWNER_URL:  # the logger cannot delete; tidy up its test rows as the owner
        with psycopg.connect(OWNER_URL, autocommit=True, connect_timeout=20) as o:
            o.execute("delete from hq_app.request_log where release = 'pytest'")


@needs_log
def test_logger_can_insert_and_read(logger):
    logger.execute("insert into hq_app.request_log (release, client_hash, question, cost_usd, prompt_versions, "
                   "cited_chunk_ids) values ('pytest', 'h', 'q', 0.000123, '{\"plan\": \"p\"}', array['a'])")
    logger.execute("select question, cost_usd, prompt_versions->>'plan', cited_chunk_ids from hq_app.request_log "
                   "where release = 'pytest' order by id desc limit 1")
    assert logger.fetchone() == ("q", __import__("decimal").Decimal("0.000123"), "p", ["a"])


@needs_log
@pytest.mark.parametrize("stmt", [
    "update hq_app.request_log set question = 'x'",
    "delete from hq_app.request_log",
    "truncate hq_app.request_log",
    "drop table hq_app.request_log",
    "select count(*) from hq.hospitals",
    "select count(*) from hq_docs.chunks",
    "create table hq_app.t (a int)",
])
def test_logger_cannot_update_delete_or_read_data(logger, stmt):
    with pytest.raises(psycopg.Error):
        logger.execute(stmt)


@needs_log
def test_logger_statement_timeout(logger):
    with pytest.raises(psycopg.errors.QueryCanceled):
        logger.execute("select pg_sleep(8)")


@needs_log
@pytest.mark.skipif(not URL, reason="HQ_READER_URL not set")
def test_reader_cannot_read_log(cur):
    with pytest.raises(psycopg.Error):
        cur.execute("select count(*) from hq_app.request_log")


@needs_log
@needs_service
def test_service_cannot_read_log(svc):
    with pytest.raises(psycopg.Error):
        svc.execute("select count(*) from hq_app.request_log")
