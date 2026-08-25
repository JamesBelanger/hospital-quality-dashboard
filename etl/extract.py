"""
extract.py — export the dashboard views to CSV for Tableau Public (which connects to files, not a live DB on the free tier)
and for the Plotly web version.

Usage: python etl/extract.py        → dashboard/extracts/{scorecard,benchmarks,hcahps,tx_vs_national}.csv
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd
import psycopg2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl")); from load import db_url  # noqa: E402
OUT = ROOT / "dashboard" / "extracts"

VIEWS = {
    "scorecard":      "SELECT * FROM hq.v_scorecard ORDER BY facility_name",
    "benchmarks":     "SELECT * FROM hq.v_benchmarks WHERE is_texas ORDER BY measure_id, facility_name",  # TX rows carry national/state avgs already
    "benchmarks_all": "SELECT measure_id, state, facility_id, score, national_avg, state_avg, national_pct_rank FROM hq.v_benchmarks",  # for national distributions
    "hcahps":         "SELECT * FROM hq.v_hcahps ORDER BY facility_name, measure_id",
    "tx_vs_national": "SELECT * FROM hq.v_tx_vs_national",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with psycopg2.connect(db_url()) as conn:
        for name, q in VIEWS.items():
            df = pd.read_sql(q, conn)
            df.to_csv(OUT / f"{name}.csv", index=False)
            print(f"{name:16s} {len(df):>8,d} rows  {df.shape[1]:>3d} cols -> dashboard/extracts/{name}.csv")


if __name__ == "__main__":
    main()
