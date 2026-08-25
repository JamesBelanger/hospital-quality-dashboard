"""
download.py — pull the six CMS Care Compare hospital datasets (all states) from data.cms.gov/provider-data.

Usage:  python etl/download.py            (downloads to data/raw/, writes data/MANIFEST.md)
        python etl/download.py --only hcahps,hospital_general

Source of truth = the provider-data metastore API; the CSV location changes every release, so we
resolve it at run time (and fall back to the datastore export endpoint if the file link is missing).
"""
from __future__ import annotations
import argparse, hashlib, sys, time
from datetime import date
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "data" / "MANIFEST.md"
API = "https://data.cms.gov/provider-data/api/1"

# key -> (dataset identifier on provider-data, human title)
DATASETS = {
    "hospital_general":     ("xubh-q36u", "Hospital General Information"),
    "unplanned_visits":     ("632h-zaca", "Unplanned Hospital Visits - Hospital"),
    "hcahps":               ("dgck-syfz", "Patient survey (HCAHPS) - Hospital"),
    "timely_effective":     ("yv7e-xc69", "Timely and Effective Care - Hospital"),
    "complications_deaths": ("ynj2-r877", "Complications and Deaths - Hospital"),
    "hai":                  ("77hc-ibv8", "Healthcare Associated Infections - Hospital"),
}


def resolve_download_url(dataset_id: str) -> tuple[str, str]:
    """Return (download_url, modified_date) for a dataset via the metastore; fall back to datastore export."""
    meta = requests.get(f"{API}/metastore/schemas/dataset/items/{dataset_id}",
                        params={"show-reference-ids": "false"}, timeout=60)
    meta.raise_for_status()
    d = meta.json()
    modified = d.get("modified", "unknown")
    try:
        url = d["distribution"][0]["data"]["downloadURL"]
    except (KeyError, IndexError, TypeError):
        url = f"{API}/datastore/query/{dataset_id}/0/download?format=csv"
    return url, modified


def download(url: str, dest: Path) -> tuple[int, str]:
    """Stream a CSV to dest; return (bytes, sha256)."""
    h = hashlib.sha256()
    n = 0
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk); h.update(chunk); n += len(chunk)
    return n, h.hexdigest()


def count_rows(path: Path) -> int:
    with open(path, "rb") as f:
        return max(sum(1 for _ in f) - 1, 0)  # minus header


def main(only: list[str] | None):
    RAW.mkdir(parents=True, exist_ok=True)
    keys = only or list(DATASETS)
    rows = []
    for key in keys:
        ds_id, title = DATASETS[key]
        url, modified = resolve_download_url(ds_id)
        dest = RAW / f"{key}.csv"
        t0 = time.time()
        nbytes, sha = download(url, dest)
        nrows = count_rows(dest)
        print(f"{key:22s} {nrows:>8,d} rows  {nbytes/1e6:6.1f} MB  {time.time()-t0:5.1f}s  (modified {modified})")
        rows.append((key, ds_id, title, modified, url, nrows, sha))

    # rewrite manifest (documented provenance; raw CSVs themselves are gitignored)
    lines = ["# Source datasets (CMS Care Compare — data.cms.gov/provider-data)", "",
             f"Retrieved {date.today().isoformat()} by etl/download.py. Raw CSVs live in data/raw/ (gitignored).", "",
             "| key | dataset id | title | CMS modified | rows | sha256 | source URL |",
             "|---|---|---|---|---|---|---|"]
    for key, ds_id, title, modified, url, nrows, sha in rows:
        lines.append(f"| {key} | {ds_id} | {title} | {modified} | {nrows:,} | {sha[:16]}… | {url} |")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nManifest written -> {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated dataset keys", default=None)
    a = ap.parse_args()
    main(a.only.split(",") if a.only else None)
