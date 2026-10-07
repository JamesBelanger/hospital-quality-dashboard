"""Part A addendum: comment-rewrite breakout tests (sqlglot turns -- comments into /* */)."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service.sql_guard import check, UnsafeSQL
C = [
 "select facility_id from hq.hospitals -- */ ; drop table hq.hospitals; /*",
 "select facility_id from hq.hospitals /* a */ ; select 1 /* b */",
 "select facility_id from hq.hospitals -- x */ select pg_sleep(8) /*",
 "select facility_id from hq.hospitals where facility_id = 'a' -- */ union select 1 /*\n",
 "select facility_id /* -- */ from hq.hospitals",
 "select facility_id from hq.hospitals --*/ ; delete from hq.hospitals --",
 "select 1 -- */ ; drop table hq.hospitals ; /* ",
 "select facility_id from hq.hospitals /* */ */ ; drop table hq.hospitals",
]
for c in C:
    try:
        out = check(c); print("ACCEPT", repr(c), "\n   =>", repr(out))
    except UnsafeSQL as e:
        print("reject", repr(c), "|", e)
