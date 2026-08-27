"""
export_web.py — build the static data bundle for the interactive explorer (dashboard/explorer/data/).

Reads data/processed/*.csv (the same tidy tables that etl/load.py COPYs into Postgres) so the explorer is
reproducible without a database connection. Writes:

  hospitals.json        all 5,419 hospitals (columnar; ZIP-centroid lat/lon from the Census ZCTA gazetteer)
  catalog.json          curated key-measure catalog (groups, direction, units) + the full measure list
  values.json           latest score per (hospital, key measure) for the ~33 key measures
  measures/<id>.json    latest scores for every measure (lazy-loaded by the measure explorer)
  sql.json              the SQL behind each panel (from sql/*.sql and sql/views.sql)
  hq/*.parquet          hospitals, measures, measure_values for the in-browser DuckDB console
  geo/*.json            us-atlas states/counties topojson (copied from assets dir if present)

Usage: python etl/export_web.py [--assets <dir with 2023_Gaz_zcta_national.txt, states-10m.json, counties-10m.json>]
"""
from __future__ import annotations
import argparse, json, re, shutil
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "dashboard" / "explorer" / "data"
(OUT / "measures").mkdir(parents=True, exist_ok=True)
(OUT / "hq").mkdir(exist_ok=True)
(OUT / "geo").mkdir(exist_ok=True)

ACR = {"LLP", "LLC", "HCA", "VA", "UT", "ED", "MD", "USA", "TMC", "NW", "SW", "SE", "NE", "PLLC", "LP", "LTD", "DBA", "CHI", "UTMB", "UCSF", "UCLA", "UPMC", "NYU", "UC", "UCI", "UCSD", "SUNY", "CHRISTUS"}
SMALL = {"of", "and", "the", "at", "in", "for", "on"}

def nice(name):
    if not isinstance(name, str):
        return name
    out = []
    for i, w in enumerate(name.split()):
        core = re.sub(r"[^A-Za-z]", "", w)
        if core.upper() in ACR:
            out.append(w.upper()); continue
        w = w.lower()
        if i and w in SMALL:
            out.append(w); continue
        out.append(re.sub(r"(^|[\-/(])([a-z])", lambda m: m.group(1) + m.group(2).upper(), w))
    return " ".join(out)

# ---------------- curated key-measure catalog ----------------
# group: outcomes | readmissions | safety | timely | experience ; hib = higher is better ; unit ; dec = decimals
CATALOG = [
    ("MORT_30_HF",   "complications_deaths", "outcomes", "Heart-failure mortality", "%", False, 1, "30-day death rate, heart-failure patients"),
    ("MORT_30_PN",   "complications_deaths", "outcomes", "Pneumonia mortality", "%", False, 1, "30-day death rate, pneumonia patients"),
    ("MORT_30_AMI",  "complications_deaths", "outcomes", "Heart-attack mortality", "%", False, 1, "30-day death rate, heart-attack patients"),
    ("MORT_30_STK",  "complications_deaths", "outcomes", "Stroke mortality", "%", False, 1, "30-day death rate, stroke patients"),
    ("MORT_30_COPD", "complications_deaths", "outcomes", "COPD mortality", "%", False, 1, "30-day death rate, COPD patients"),
    ("Hybrid_HWM",   "complications_deaths", "outcomes", "Hospital-wide mortality", "%", False, 2, "Hybrid hospital-wide risk-standardized mortality"),
    ("READM_30_PN",  "unplanned_visits", "readmissions", "Pneumonia readmission", "%", False, 1, "30-day readmission, pneumonia"),
    ("READM_30_HF",  "unplanned_visits", "readmissions", "Heart-failure readmission", "%", False, 1, "30-day readmission, heart failure"),
    ("READM_30_AMI", "unplanned_visits", "readmissions", "Heart-attack readmission", "%", False, 1, "30-day readmission, heart attack"),
    ("READM_30_COPD","unplanned_visits", "readmissions", "COPD readmission", "%", False, 1, "30-day readmission, COPD"),
    ("READM_30_HIP_KNEE", "unplanned_visits", "readmissions", "Hip/knee readmission", "%", False, 1, "Readmission after hip/knee replacement"),
    ("EDAC_30_HF",   "unplanned_visits", "readmissions", "HF return days", "days/100", False, 1, "Excess days in acute care per 100 heart-failure discharges"),
    ("HAI_1_SIR",    "hai", "safety", "Central-line infections", "SIR", False, 2, "CLABSI standardized infection ratio (1.0 = as predicted)"),
    ("HAI_2_SIR",    "hai", "safety", "Catheter UTIs", "SIR", False, 2, "CAUTI standardized infection ratio"),
    ("HAI_3_SIR",    "hai", "safety", "Colon-surgery infections", "SIR", False, 2, "SSI colon surgery, standardized infection ratio"),
    ("HAI_5_SIR",    "hai", "safety", "MRSA bacteremia", "SIR", False, 2, "MRSA standardized infection ratio"),
    ("HAI_6_SIR",    "hai", "safety", "C. diff infections", "SIR", False, 2, "C. difficile standardized infection ratio"),
    ("PSI_90",       "complications_deaths", "safety", "Patient-safety composite", "index", False, 2, "CMS PSI-90 composite of adverse events (1.0 = expected)"),
    ("COMP_HIP_KNEE","complications_deaths", "safety", "Hip/knee complications", "%", False, 1, "Complication rate after hip/knee replacement"),
    ("OP_18b",       "timely_effective", "timely", "ED time to discharge", "min", False, 0, "Median minutes in the ED before leaving"),
    ("OP_22",        "timely_effective", "timely", "Left ED without being seen", "%", False, 1, "Share of ED patients who left before being seen"),
    ("SEP_1",        "timely_effective", "timely", "Sepsis bundle", "%", True, 0, "Appropriate care for severe sepsis and septic shock"),
    ("IMM_3",        "timely_effective", "timely", "Staff flu vaccination", "%", True, 0, "Healthcare workers given influenza vaccination"),
    ("SAFE_USE_OF_OPIOIDS", "timely_effective", "timely", "Safe opioid prescribing", "%", True, 0, "Safe use of opioids, concurrent prescribing"),
    ("H_STAR_RATING","hcahps", "experience", "Patient-experience stars", "stars", True, 0, "HCAHPS summary star rating"),
    ("H_RECMND_DY",  "hcahps", "experience", "Would recommend", "%", True, 0, "Patients who would definitely recommend the hospital"),
    ("H_HSP_RATING_9_10", "hcahps", "experience", "Rated 9-10", "%", True, 0, "Patients rating the hospital 9 or 10 of 10"),
    ("H_COMP_1_A_P", "hcahps", "experience", "Nurses communicated", "%", True, 0, "Nurses always communicated well"),
    ("H_COMP_2_A_P", "hcahps", "experience", "Doctors communicated", "%", True, 0, "Doctors always communicated well"),
    ("H_COMP_5_A_P", "hcahps", "experience", "Medicines explained", "%", True, 0, "Staff always explained medicines"),
    ("H_COMP_6_Y_P", "hcahps", "experience", "Discharge information", "%", True, 0, "Given information about recovery at home"),
    ("H_CLEAN_HSP_A_P", "hcahps", "experience", "Room clean", "%", True, 0, "Room and bathroom always clean"),
    ("H_QUIET_HSP_A_P", "hcahps", "experience", "Quiet at night", "%", True, 0, "Area around room always quiet at night"),
]
GROUPS = {"outcomes": "Mortality", "readmissions": "Readmissions", "safety": "Safety", "timely": "Timely care", "experience": "Patient experience"}
# direction overrides for the full list where the ETL heuristic is wrong
HIB_OVERRIDE = {"H_RECMND_DN": False, "HH_HYPO": False, "HH_HYPER": False, "HH_ORAE": False, "OP_29": True, "OP_31": True}
HIDE_RE = re.compile(r"_(NUMERATOR|ELIGCASES|DOPC|CIUPPER|CILOWER)$|_(SN|U|N|PY|DN)_P$|_(U|SN|N)_P$|H_RECMND_PY|H_RECMND_DN|H_HSP_RATING_(0_6|7_8)")

def main(assets: Path | None):
    h = pd.read_csv(PROC / "hospitals.csv", dtype={"facility_id": str, "zip_code": str})
    m = pd.read_csv(PROC / "measures.csv")
    v = pd.read_csv(PROC / "measure_values.csv", dtype={"facility_id": str}, low_memory=False)
    v = v[v.score.notna()].copy()
    v["period_end"] = pd.to_datetime(v.period_end, errors="coerce")
    latest = (v.sort_values("period_end").groupby(["facility_id", "measure_id", "domain"], as_index=False).tail(1))

    # ---- hospitals (columnar) ----
    h = h.sort_values("facility_id").reset_index(drop=True)
    idx = {fid: i for i, fid in enumerate(h.facility_id)}
    lat = lon = None
    if assets and (assets / "2023_Gaz_zcta_national.txt").exists():
        gz = pd.read_csv(assets / "2023_Gaz_zcta_national.txt", sep="\t", dtype={"GEOID": str})
        gz.columns = [c.strip() for c in gz.columns]
        zc = dict(zip(gz.GEOID, zip(gz.INTPTLAT, gz.INTPTLONG)))
        z5 = h.zip_code.fillna("").str.extract(r"(\d{5})")[0]
        pts = z5.map(zc)
        lat = pts.map(lambda p: round(p[0], 4) if isinstance(p, tuple) else None)
        lon = pts.map(lambda p: round(p[1], 4) if isinstance(p, tuple) else None)
        print(f"geocoded {pts.notna().sum()}/{len(h)} hospitals by ZIP centroid")
    hosp = {
        "cols": ["id", "name", "city", "state", "zip", "county", "type", "own", "er", "stars", "tx", "hou", "lat", "lon"],
        "rows": [[r.facility_id, nice(r.facility_name), nice(str(r.city)) if pd.notna(r.city) else None, r.state,
                  (str(r.zip_code)[:5] if pd.notna(r.zip_code) else None), nice(str(r.county)) if pd.notna(r.county) else None,
                  r.hospital_type, r.hospital_ownership, (r.emergency_services == "Yes"),
                  (int(r.overall_rating) if pd.notna(r.overall_rating) else None), bool(r.is_texas), bool(r.is_houston_area),
                  (None if lat is None or pd.isna(lat[i]) else float(lat[i])), (None if lon is None or pd.isna(lon[i]) else float(lon[i]))]
                 for i, r in enumerate(h.itertuples())],
    }
    (OUT / "hospitals.json").write_text(json.dumps(hosp, separators=(",", ":")), encoding="utf-8")

    # ---- catalog + values for key measures ----
    cov = latest.groupby(["measure_id", "domain"]).facility_id.nunique()
    key = []
    values = {}
    for mid, dom, grp, short, unit, hib, dec, desc in CATALOG:
        sub = latest[(latest.measure_id == mid) & (latest.domain == dom)]
        if sub.empty:
            print("WARN: no rows for", mid); continue
        key.append({"id": mid, "domain": dom, "group": grp, "short": short, "unit": unit, "hib": hib, "dec": dec, "desc": desc,
                    "n": int(sub.facility_id.nunique()), "period": [str(sub.period_start.min())[:10], str(sub.period_end.max().date())]})
        values[mid] = {"i": [idx[f] for f in sub.facility_id], "v": [round(float(s), 3) for s in sub.score],
                       "d": [None if pd.isna(d) else int(d) for d in sub.denominator]}
    # full list (for the measure explorer)
    names = m.groupby(["measure_id", "domain"]).agg(name=("measure_name", "first"), vt=("value_type", "first"), hib=("higher_is_better", "first")).reset_index()
    allm = []
    for r in names.itertuples():
        n = int(cov.get((r.measure_id, r.domain), 0))
        if n == 0: continue
        hib = HIB_OVERRIDE.get(r.measure_id, None if pd.isna(r.hib) else bool(r.hib))
        allm.append({"id": r.measure_id, "domain": r.domain, "name": str(r.name).split(" — ")[0][:140], "vt": r.vt, "hib": hib, "n": n,
                     "hidden": bool(HIDE_RE.search(r.measure_id)), "key": r.measure_id in values})
        sub = latest[(latest.measure_id == r.measure_id) & (latest.domain == r.domain)]
        fn = OUT / "measures" / f"{r.measure_id}.json"
        if fn.exists() and r.measure_id in {a["id"] for a in allm[:-1]}:  # id collision across domains
            fn = OUT / "measures" / f"{r.measure_id}__{r.domain}.json"; allm[-1]["file"] = fn.name
        fn.write_text(json.dumps({"i": [idx[f] for f in sub.facility_id], "v": [round(float(s), 3) for s in sub.score]}, separators=(",", ":")), encoding="utf-8")
    catalog = {"groups": GROUPS, "key": key, "all": sorted(allm, key=lambda a: -a["n"]), "n_hospitals": len(h),
               "n_values": int(len(v)), "n_measures": len(allm), "release": "July 2026"}
    (OUT / "catalog.json").write_text(json.dumps(catalog, separators=(",", ":")), encoding="utf-8")
    (OUT / "values.json").write_text(json.dumps(values, separators=(",", ":")), encoding="utf-8")
    print(f"key measures {len(key)}, all measures {len(allm)}, values {sum(len(x['v']) for x in values.values())}")

    # ---- SQL snippets ----
    sql = {}
    for f in sorted((ROOT / "sql").glob("[0-9][0-9]_*.sql")):
        sql[f.stem] = f.read_text(encoding="utf-8")
    sql["views"] = (ROOT / "sql" / "views.sql").read_text(encoding="utf-8")
    sql["schema"] = (ROOT / "schema.sql").read_text(encoding="utf-8")
    (OUT / "sql.json").write_text(json.dumps(sql), encoding="utf-8")

    # ---- parquet for DuckDB-WASM ----
    hp = h.copy(); hp["overall_rating"] = hp.overall_rating.astype("Int64")
    pq.write_table(pa.Table.from_pandas(hp, preserve_index=False), OUT / "hq" / "hospitals.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pandas(m, preserve_index=False), OUT / "hq" / "measures.parquet", compression="zstd")
    mv = v[["facility_id", "measure_id", "domain", "measure_name", "score", "denominator", "lower_estimate", "upper_estimate", "compared_to_national", "value_type", "period_start", "period_end"]].copy()
    mv["period_start"] = pd.to_datetime(mv.period_start, errors="coerce").dt.date
    mv["period_end"] = mv.period_end.dt.date
    for c in ["score", "denominator", "lower_estimate", "upper_estimate"]:
        mv[c] = pd.to_numeric(mv[c], errors="coerce").astype("float64")
    pq.write_table(pa.Table.from_pandas(mv, preserve_index=False), OUT / "hq" / "measure_values.parquet", compression="zstd")

    # ---- geo ----
    if assets:
        for fn in ["states-10m.json", "counties-10m.json"]:
            if (assets / fn).exists(): shutil.copy(assets / fn, OUT / "geo" / fn)
    for p in sorted(OUT.rglob("*")):
        if p.is_file() and p.parent.name != "measures":
            print(f"{p.relative_to(OUT)}  {p.stat().st_size/1e6:.2f} MB")
    print(f"measures/  {len(list((OUT/'measures').glob('*.json')))} files, {sum(p.stat().st_size for p in (OUT/'measures').glob('*.json'))/1e6:.1f} MB total")

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--assets", type=Path, default=None)
    a = ap.parse_args(); main(a.assets)
