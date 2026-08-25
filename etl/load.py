"""
load.py — create the schema and bulk-load data/processed/*.csv into Postgres (Supabase).

Requires .env with DATABASE_URL=postgresql://... (gitignored; never print it).
Usage:  python etl/load.py            (drops + recreates hq.* tables, loads all three)
        python etl/load.py --check    (row counts only)

Uses COPY via psycopg2 for speed (~800k fact rows in well under a minute on the free tier).
"""
from __future__ import annotations
import argparse, io, os, sys
from pathlib import Path
import pandas as pd
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
SCHEMA = ROOT / "schema.sql"


def db_url() -> str:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL not found: create .env (see .env.example)")
    return url


def copy_df(cur, df: pd.DataFrame, table: str, cols: list[str]):
    buf = io.StringIO()
    df[cols].to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    cur.copy_expert(f"COPY hq.{table} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv, NULL '')", buf)


def load():
    hospitals = pd.read_csv(PROC / "hospitals.csv", dtype=str, keep_default_na=False)
    measures = pd.read_csv(PROC / "measures.csv", dtype=str, keep_default_na=False)
    values = pd.read_csv(PROC / "measure_values.csv", dtype=str, keep_default_na=False)
    # booleans → 't'/'f' for COPY; blanks stay NULL
    for c in ("is_texas", "is_houston_area"):
        hospitals[c] = hospitals[c].map({"True": "t", "False": "f"}).fillna("f")
    measures["higher_is_better"] = measures["higher_is_better"].map({"True": "t", "False": "f"}).fillna("")
    # integer columns: pandas round-trips them as "4.0"; Postgres smallint/integer wants "4"
    def as_int_str(col):
        return pd.to_numeric(col, errors="coerce").round().astype("Int64").astype(str).replace({"<NA>": ""})
    hospitals["overall_rating"] = as_int_str(hospitals["overall_rating"])
    measures["n_rows"] = as_int_str(measures["n_rows"])

    with psycopg2.connect(db_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA.read_text(encoding="utf-8"))
            copy_df(cur, hospitals, "hospitals",
                    ["facility_id","facility_name","address","city","state","zip_code","county","hospital_type",
                     "hospital_ownership","emergency_services","overall_rating","is_texas","is_houston_area"])
            copy_df(cur, measures, "measures", ["measure_id","domain","measure_name","value_type","n_rows","higher_is_better"])
            copy_df(cur, values, "measure_values",
                    ["facility_id","measure_id","domain","measure_name","score","denominator","lower_estimate",
                     "upper_estimate","compared_to_national","value_type","period_start","period_end"])
        conn.commit()
    check()


def check():
    with psycopg2.connect(db_url()) as conn, conn.cursor() as cur:
        for t in ("hospitals", "measures", "measure_values"):
            cur.execute(f"SELECT count(*) FROM hq.{t}")
            print(f"hq.{t:15s} {cur.fetchone()[0]:>10,d} rows")
        cur.execute("SELECT count(*) FROM hq.hospitals WHERE is_houston_area")
        print(f"Houston-area hospitals: {cur.fetchone()[0]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    check() if a.check else load()
