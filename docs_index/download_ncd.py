"""
download_ncd.py — fetch every current Medicare National Coverage Determination (NCD) from the CMS Coverage API.

Usage:  python docs_index/download_ncd.py            (raw JSON -> docs_index/raw/ncd/, manifest -> docs_index/manifest_ncd.json)
        python docs_index/download_ncd.py --limit 5   (first 5 only, for a smoke test)

Source: https://api.coverage.cms.gov (public; the NCD endpoints need no license token). NCDs ONLY: the
Local Coverage Determination and Article endpoints need a license-agreement token and carry AMA-licensed CPT
content, so they are not used here. One request at a time, a short delay between requests, retries with backoff.
raw/ is gitignored; the manifest is tracked so the exact bytes (sha256) behind every cited chunk are recorded.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw" / "ncd"
MANIFEST = ROOT / "manifest_ncd.json"
API = "https://api.coverage.cms.gov/v1"
LIST_URL = f"{API}/reports/national-coverage-ncd/"
DOC_URL = f"{API}/data/ncd/?ncdid={{id}}&ncdver={{ver}}"
PUBLIC_URL = "https://www.cms.gov/medicare-coverage-database/view/ncd.aspx?ncdid={id}&ncdver={ver}"
UA = "hospital-quality-dashboard docs_index (polite, sequential)"
DELAY_S = 0.4


def get(url: str, tries: int = 5) -> requests.Response:
    for i in range(tries):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            if r.status_code == 200:
                return r
            err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            err = type(e).__name__
        wait = 2 ** i
        print(f"  retry {i + 1}/{tries} after {err}; sleeping {wait}s", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError(f"giving up on {url}")


def main(limit: int | None):
    RAW.mkdir(parents=True, exist_ok=True)
    listing = get(LIST_URL).json()["data"]
    listing = sorted(listing, key=lambda x: (int(x["document_id"]), int(x["document_version"])))
    print(f"{len(listing)} current NCDs listed")
    docs, problems = [], []
    for n, item in enumerate(listing[:limit] if limit else listing, 1):
        nid, ver = int(item["document_id"]), int(item["document_version"])
        time.sleep(DELAY_S)
        r = get(DOC_URL.format(id=nid, ver=ver))
        body = r.content
        rows = json.loads(body)["data"]
        if len(rows) != 1:
            problems.append(f"ncdid={nid} ver={ver}: {len(rows)} rows returned")
            continue
        d = rows[0]
        dest = RAW / f"ncd_{nid}_v{ver}.json"
        dest.write_bytes(body)
        number = d["document_display_id"].strip()
        end_date = (d.get("effective_end_date") or "").strip()
        end_date = None if end_date in ("", "N/A") else end_date  # "N/A" = still in force
        docs.append(dict(
            doc_id=f"ncd_{number}", ncd_id=nid, manual_section=number, title=d["title"].strip(),
            publication_number=d.get("publication_number"), version=ver,
            effective_date=d.get("effective_date") or None, effective_end_date=end_date,
            implementation_date=d.get("implementation_date") or None,
            publisher="CMS Medicare Coverage Database (National Coverage Determination)",
            source_url=PUBLIC_URL.format(id=nid, ver=ver), api_url=DOC_URL.format(id=nid, ver=ver),
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), file=f"ncd/{dest.name}"))
        if n % 50 == 0:
            print(f"  {n} fetched", flush=True)
    MANIFEST.write_text(json.dumps({"documents": docs, "problems": problems}, indent=2) + "\n", encoding="utf-8")
    print(f"{len(docs)} NCDs fetched; problems: {problems or 'none'}; manifest -> {MANIFEST.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    main(a.limit)
