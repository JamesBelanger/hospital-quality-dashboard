"""Part B (timing / size): timeout enforcement and big-value behaviour as hq_reader, rolled back."""
import json
import time
from pathlib import Path

import psycopg
from dotenv import dotenv_values

env = dotenv_values(Path(__file__).resolve().parents[1] / ".env")
URL = env["HQ_READER_URL"]
SVC = env["HQ_SERVICE_URL"]
res = []


def go(label, sql, url=URL, fetch="all", pre=None):
    t0 = time.perf_counter()
    conn = psycopg.connect(url, autocommit=False, connect_timeout=30)
    try:
        cur = conn.cursor()
        for p in pre or []:
            cur.execute(p)
        cur.execute(sql)
        rows = cur.fetchall() if fetch == "all" else cur.fetchone()
        r = repr(rows)
        out = ("ALLOWED", r[:120] + (f"...(repr len {len(r)})" if len(r) > 120 else ""))
    except psycopg.Error as e:
        out = ("ERR", f"{type(e).__name__}: {str(e).strip().splitlines()[0][:150]}")
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        conn.close()
    el = round(time.perf_counter() - t0, 2)
    res.append({"label": label, "status": out[0], "detail": out[1], "elapsed_s": el})
    print(f"{label[:60]:60s} | {out[0]:7s} | {el:6.2f}s | {out[1]}", flush=True)


go("pg_sleep(8) as hq_reader", "select pg_sleep(8)")
go("pg_sleep(12) as hq_service", "select pg_sleep(12)", url=SVC)
go("cross join 3x measure_values count", "select count(*) from hq.measure_values a, hq.measure_values b, hq.measure_values c")
go("recursive CTE unbounded count", "with recursive r(n) as (select 1 union all select n+1 from r) select count(*) from r")
go("generate_series(1,1e9) count", "select count(*) from (select generate_series(1,1000000000)) s")
go("catastrophic regex over hospitals", "select count(*) from hq.hospitals where repeat('a',40)||'!' ~ '(a+)+$'")
go("server-side length(repeat 'x' 200M)", "select length(repeat('x', 200000000))")
go("server-side length(repeat 'x' 1e9)", "select length(repeat('x', 1000000000))")
go("fetch repeat('x', 20M) to client", "select repeat('x', 20000000)")
go("fetch 200 rows x 1M chars (guard row cap allows)", "select repeat('y', 1000000) from generate_series(1,200)")
go("fetch repeat('x',100M) to client", "select repeat('x', 100000000)")
go("pg_stat_statements text visible to hq_service?", "select count(*) filter (where query not like '<insufficient%'), count(*) from extensions.pg_stat_statements", url=SVC)
go("timeout survives: set 0 then pg_sleep(8) (needs SET)", "select pg_sleep(8)", pre=["set statement_timeout = 0"])
Path(__file__).with_name("part_b2_results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
