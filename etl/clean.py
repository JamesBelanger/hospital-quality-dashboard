"""
clean.py — turn the six raw CMS CSVs into a tidy, load-ready set of tables.

Outputs (data/processed/, gitignored):
  hospitals.csv       one row per facility (dimension) + is_texas / is_houston_area flags
  measures.csv        one row per measure (dimension) with domain + higher_is_better heuristic
  measure_values.csv  long/tidy fact table: facility_id, measure_id, score, denominator, lower/upper, period, value_type

Design notes (interview talking points):
  * Long/tidy fact table instead of one wide table per dataset: every CMS file has a different column set,
    but they all reduce to (facility, measure, period, value). One shape = one schema = one set of SQL.
  * Benchmarks (state / national) are NOT loaded from CMS's separate benchmark files on purpose —
    computing them in SQL from the hospital-level data is exercise material (window functions).
  * "Not Available" / "Not Applicable" / blanks become NULL, never 0.
"""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
HOUSTON_COUNTIES = {"HARRIS", "FORT BEND", "MONTGOMERY", "BRAZORIA", "GALVESTON"}
NA_TOKENS = {"", "Not Available", "Not Applicable", "N/A", "NA", "--", "Number of Cases Too Small"}


def norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [re.sub(r"[^a-z0-9]+", "_", c.strip().lower()).strip("_") for c in df.columns]
    return df


def read(key: str) -> pd.DataFrame:
    return norm_cols(pd.read_csv(RAW / f"{key}.csv", dtype=str, keep_default_na=False, encoding="utf-8-sig"))


def to_num(s: pd.Series) -> pd.Series:
    s = s.astype(str).str.strip()
    s = s.where(~s.isin(NA_TOKENS), np.nan)
    return pd.to_numeric(s.str.replace(",", "", regex=False), errors="coerce")


def to_date(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, errors="coerce").dt.date


def pick(df: pd.DataFrame, *candidates: str) -> pd.Series:
    """First existing column among candidates, else an all-NaN series."""
    for c in candidates:
        if c in df.columns:
            return df[c]
    return pd.Series([np.nan] * len(df), index=df.index)


# ---------- hospitals dimension ----------
def build_hospitals() -> pd.DataFrame:
    g = read("hospital_general")
    h = pd.DataFrame({
        "facility_id": g["facility_id"].str.strip(),
        "facility_name": g["facility_name"].str.strip(),
        "address": pick(g, "address"),
        "city": pick(g, "city_town", "city").str.strip(),
        "state": g["state"].str.strip(),
        "zip_code": pick(g, "zip_code").str.strip(),
        "county": pick(g, "county_parish", "county_name", "county").str.strip().str.upper(),
        "hospital_type": pick(g, "hospital_type"),
        "hospital_ownership": pick(g, "hospital_ownership"),
        "emergency_services": pick(g, "emergency_services"),
        "overall_rating": to_num(pick(g, "hospital_overall_rating")),
    })
    h["is_texas"] = h["state"].eq("TX")
    h["is_houston_area"] = h["is_texas"] & h["county"].isin(HOUSTON_COUNTIES)
    return h.drop_duplicates("facility_id")


# ---------- generic measure datasets ----------
def tidy_generic(key: str, domain: str) -> pd.DataFrame:
    d = read(key)
    return pd.DataFrame({
        "facility_id": d["facility_id"].str.strip(),
        "measure_id": d["measure_id"].str.strip(),
        "measure_name": pick(d, "measure_name").str.strip(),
        "domain": domain,
        "score": to_num(pick(d, "score")),
        "denominator": to_num(pick(d, "denominator", "sample")),
        "lower_estimate": to_num(pick(d, "lower_estimate")),
        "upper_estimate": to_num(pick(d, "higher_estimate", "upper_estimate")),
        "compared_to_national": pick(d, "compared_to_national").replace({"": np.nan}),
        "value_type": "score",
        "period_start": to_date(pick(d, "start_date")),
        "period_end": to_date(pick(d, "end_date")),
    })


# ---------- HCAHPS (different layout: question rows with several value columns) ----------
def tidy_hcahps() -> pd.DataFrame:
    d = read("hcahps")
    mid = d["hcahps_measure_id"].str.strip()
    pct = to_num(pick(d, "hcahps_answer_percent"))
    lin = to_num(pick(d, "hcahps_linear_mean_value"))
    star = to_num(pick(d, "patient_survey_star_rating"))
    # one value per row; record which kind it is so SQL can filter sensibly
    score = pct.where(pct.notna(), lin.where(lin.notna(), star))
    value_type = np.select([pct.notna(), lin.notna(), star.notna()], ["answer_percent", "linear_mean", "star_rating"], default="none")
    name = (pick(d, "hcahps_question").str.strip() + " — " + pick(d, "hcahps_answer_description").str.strip()).str.strip(" —")
    return pd.DataFrame({
        "facility_id": d["facility_id"].str.strip(),
        "measure_id": mid,
        "measure_name": name,
        "domain": "hcahps",
        "score": score,
        "denominator": to_num(pick(d, "number_of_completed_surveys")),
        "lower_estimate": np.nan,
        "upper_estimate": np.nan,
        "compared_to_national": np.nan,
        "value_type": value_type,
        "period_start": to_date(pick(d, "start_date")),
        "period_end": to_date(pick(d, "end_date")),
    })


# ---------- measures dimension (with a documented higher-is-better heuristic) ----------
LOWER_IS_BETTER_PATTERNS = [
    r"^READM_", r"^MORT_", r"^COMP_", r"^PSI_", r"^HAI_", r"^EDAC_", r"^OP_32", r"^OP_35", r"^OP_36",   # readmission/mortality/complication/infection/excess days
    r"^OP_18", r"^OP_22", r"^ED_2", r"^OP_20", r"^OP_21",                                              # ED wait times / left without being seen
    r"^OP_3", r"^OP_29", r"^OP_30", r"^OP_8", r"^OP_10", r"^OP_11", r"^OP_13", r"^OP_14",             # imaging over-use style rates (lower better)
]


def higher_is_better(measure_id: str, domain: str, name: str) -> object:
    if domain in {"unplanned_visits", "complications_deaths", "hai"}:
        return False
    if any(re.match(p, measure_id) for p in LOWER_IS_BETTER_PATTERNS):
        return False
    if domain == "hcahps":
        n = (name or "").lower()
        if any(t in n for t in ["always", "9 or 10", "definitely", "strongly agree", "linear mean", "star"]):
            return True
        return None  # "sometimes/never" answer rows etc. — leave for SQL to decide
    return True  # timely & effective process measures are mostly "% who received X"


def build_measures(values: pd.DataFrame) -> pd.DataFrame:
    m = (values.groupby(["measure_id", "domain"], as_index=False)
               .agg(measure_name=("measure_name", "first"), value_type=("value_type", "first"), n_rows=("facility_id", "size")))
    m["higher_is_better"] = [higher_is_better(i, d, n) for i, d, n in zip(m.measure_id, m.domain, m.measure_name)]
    return m.sort_values(["domain", "measure_id"]).reset_index(drop=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hospitals = build_hospitals()
    parts = [
        tidy_generic("unplanned_visits", "unplanned_visits"),
        tidy_generic("timely_effective", "timely_effective"),
        tidy_generic("complications_deaths", "complications_deaths"),
        tidy_generic("hai", "hai"),
        tidy_hcahps(),
    ]
    values = pd.concat(parts, ignore_index=True)
    values = values[values["facility_id"].isin(hospitals["facility_id"])]   # orphan guard
    measures = build_measures(values)

    hospitals.to_csv(OUT / "hospitals.csv", index=False)
    measures.to_csv(OUT / "measures.csv", index=False)
    values.to_csv(OUT / "measure_values.csv", index=False)

    tx = hospitals["is_texas"].sum(); hou = hospitals["is_houston_area"].sum()
    print(f"hospitals: {len(hospitals):,} (Texas {tx:,}, Houston-area {hou:,})")
    print(f"measures:  {len(measures):,} across domains {sorted(measures.domain.unique())}")
    print(f"values:    {len(values):,} rows; non-null scores {values.score.notna().sum():,} ({values.score.notna().mean():.0%})")
    print(values.groupby("domain").size().rename("rows").to_string())


if __name__ == "__main__":
    main()
