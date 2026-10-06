"""service.db with a fake connection: reuse, reconnect once, second failure propagates, timeouts not retried."""
import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import db  # noqa: E402


class FakeConn:
    def __init__(self, fail_times=0, exc=psycopg.OperationalError):
        self.fail_times, self.exc, self.closed, self.queries = fail_times, exc, False, 0

    def cursor(self):
        return self

    def execute(self, q):
        self.queries += 1
        if self.fail_times:
            self.fail_times -= 1
            raise self.exc("server closed the connection")
        return q

    def close(self):
        self.closed = True


@pytest.fixture()
def conns(monkeypatch):
    made = []
    plan = []  # FakeConn objects handed out in order

    def connect(url):
        c = plan.pop(0) if plan else FakeConn()
        made.append(c)
        return c

    db.close_all()
    monkeypatch.setattr(db, "_connect", connect)
    yield made, plan
    db.close_all()


def test_connection_is_opened_once_and_reused(conns):
    made, _ = conns
    for _i in range(3):
        db.run("u1", lambda cur: cur.execute("select 1"))
    assert len(made) == 1 and made[0].queries == 3


def test_one_connection_per_url(conns):
    made, _ = conns
    db.run("u1", lambda cur: cur.execute("x"))
    db.run("u2", lambda cur: cur.execute("x"))
    assert len(made) == 2


def test_dropped_connection_reconnects_once_and_retries(conns):
    made, plan = conns
    plan.extend([FakeConn(fail_times=1), FakeConn()])
    assert db.run("u1", lambda cur: cur.execute("select 1")) == "select 1"
    assert len(made) == 2 and made[0].closed and made[1].queries == 1


def test_second_failure_propagates(conns):
    made, plan = conns
    plan.extend([FakeConn(fail_times=1), FakeConn(fail_times=1)])
    with pytest.raises(psycopg.OperationalError):
        db.run("u1", lambda cur: cur.execute("select 1"))
    assert len(made) == 2


def test_statement_timeout_is_not_retried(conns):
    made, plan = conns
    plan.append(FakeConn(fail_times=5, exc=psycopg.errors.QueryCanceled))
    with pytest.raises(psycopg.errors.QueryCanceled):
        db.run("u1", lambda cur: cur.execute("select pg_sleep(9)"))
    assert len(made) == 1 and made[0].queries == 1 and not made[0].closed


def test_other_database_errors_are_not_retried(conns):
    made, plan = conns
    plan.append(FakeConn(fail_times=5, exc=psycopg.errors.UndefinedColumn))
    with pytest.raises(psycopg.errors.UndefinedColumn):
        db.run("u1", lambda cur: cur.execute("select nope"))
    assert len(made) == 1 and made[0].queries == 1
