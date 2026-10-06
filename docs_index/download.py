"""
download.py — fetch the official CMS / HCAHPS documentation that defines the Care Compare measures.

Usage:  python docs_index/download.py          (downloads to docs_index/raw/, writes docs_index/manifest.json)
        python docs_index/download.py --only hcahps_fact_sheet

Public, no-login sources only; one request per document. raw/ is gitignored, manifest.json is tracked
so the exact bytes (sha256) behind every cited chunk are recorded.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
MANIFEST = ROOT / "manifest.json"
UA = "Mozilla/5.0 (hospital-quality-dashboard docs_index; polite single-fetch)"

SOURCES = [
    dict(doc_id="cms_hospital_data_dictionary",
         title="Hospital Downloadable Database Data Dictionary (July 2026)",
         publisher="CMS Provider Data Catalog",
         source_url="https://data.cms.gov/provider-data/sites/default/files/data_dictionaries/hospital/HOSPITAL_Data_Dictionary.pdf"),
    dict(doc_id="cms_hybrid_hwr_methodology",
         title="Hybrid Hospital-Wide Readmission Measure with Electronic Health Record Extracted Risk Factors, Methodology Report v1.2 (March 2023)",
         publisher="CMS / Yale CORE",
         source_url="https://www.cms.gov/files/document/hybrid-hospital-wide-readmission-methodology-report-03202023.pdf"),
    dict(doc_id="cms_hybrid_hwm_methodology",
         title="Hybrid Hospital-Wide (All-Condition, All-Procedure) Risk-Standardized Mortality Measure with EHR Extracted Risk Factors, Methodology Report v2.1",
         publisher="CMS / Yale CORE",
         source_url="https://www.cms.gov/files/document/hybrid-hospital-wide-all-condition-all-procedure-risk-standardized-mortality-measure-electronic.pdf"),
    dict(doc_id="hcahps_fact_sheet",
         title="HCAHPS Fact Sheet (CAHPS Hospital Survey), December 2024",
         publisher="CMS HCAHPS Project Team",
         source_url="https://hcahpsonline.org/globalassets/hcahps/facts/hcahps_fact_sheet_december_2024.pdf"),
    dict(doc_id="hcahps_star_tech_notes",
         title="Technical Notes for HCAHPS Star Ratings (January 2024 Public Reporting)",
         publisher="CMS HCAHPS Project Team",
         source_url="https://hcahpsonline.org/globalassets/hcahps/star-ratings/tech-notes/january-2024_star-ratings_tech-notes.pdf"),
    # Dropped 2026-10-05: the only fetchable CMS star-rating PDF is the February 2019 public-input request,
    # which is partly proposals and superseded by the current methodology. A question-answering index
    # should not cite it. Add the current Overall Star Rating methodology PDF here when it can be obtained
    # (QualityNet serves it from a JavaScript app; download by hand).
    dict(doc_id="cms_bpci_sep1_fact_sheet",
         title="Quality Measures Fact Sheet: Severe Sepsis and Septic Shock: Management Bundle (SEP-1), BPCI Advanced (August 2020)",
         publisher="CMS Innovation Center",
         source_url="https://www.cms.gov/priorities/innovation/media/document/bpci-advanced-alt-fs-my4-sepsis"),
    dict(doc_id="cms_bpci_psi90_fact_sheet",
         title="Quality Measures Fact Sheet: Patient Safety Indicators (PSI 90), BPCI Advanced (October 2020)",
         publisher="CMS Innovation Center",
         source_url="https://www.cms.gov/priorities/innovation/media/document/bpciadvancedmy123psi90fact-sheet"),
]


def fetch(src: dict) -> dict:
    r = requests.get(src["source_url"], headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "").split(";")[0].strip()
    body = r.content
    ext = ".pdf" if ctype == "application/pdf" or body[:5] == b"%PDF-" else ".html"
    dest = RAW / f"{src['doc_id']}{ext}"
    dest.write_bytes(body)
    rec = dict(src, retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
               sha256=hashlib.sha256(body).hexdigest(), bytes=len(body), content_type=ctype,
               file=dest.name)
    if ext == ".pdf":
        import pymupdf
        with pymupdf.open(dest) as d:
            rec["pages"] = len(d)
    return rec


def main(only: list[str] | None):
    RAW.mkdir(parents=True, exist_ok=True)
    old = {d["doc_id"]: d for d in json.loads(MANIFEST.read_text("utf-8"))["documents"]} if MANIFEST.exists() else {}
    for src in SOURCES:
        if only and src["doc_id"] not in only:
            continue
        rec = fetch(src)
        old[src["doc_id"]] = rec
        print(f"{rec['doc_id']:34s} {rec['bytes']/1e3:9.0f} KB  pages={rec.get('pages','-')}  {rec['content_type']}")
    docs = [old[s["doc_id"]] for s in SOURCES if s["doc_id"] in old]
    MANIFEST.write_text(json.dumps({"documents": docs}, indent=2) + "\n", encoding="utf-8")
    print(f"Manifest written -> {MANIFEST.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    main(a.only.split(",") if a.only else None)
