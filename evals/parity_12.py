"""Parity check: can ask() reproduce the 12 hand-written, verified SQL exercises?

Each exercise in sql/EXERCISES.md has a verified query (sql/NN_*.sql). Here each one is posed as a
plain-language question; the generated SQL's result is compared with the truth query's result,
both run through the same guard, the same read-only login and the same 200-row cap.

Comparison (numbers rounded to 2 decimals). The key of a truth row is its first text value.
  match    every truth row's numeric values appear in a generated row that contains its key
  partial  at least half the truth rows match
  miss     otherwise (a refusal or a SQL error is a miss; `refused` and `sql_error` are recorded)

Usage:  python -m evals.parity_12 [--label NAME] [--plan plan_v1] [--schema schema_v1] [--answer answer_v1] [--only 01 05]
Results are appended as one run per invocation to evals/results/parity_12_<UTC date>.json.
"""
from __future__ import annotations

import argparse
import datetime
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from service import pipeline  # noqa: E402
from service.embedder import OpenAIEmbedder  # noqa: E402
from service.llm import OpenAILLM  # noqa: E402
from service.sql_runner import run_sql  # noqa: E402

QUESTIONS = {
    "01": "List every Houston-area hospital with its county, ownership, overall star rating and its latest "
          "pneumonia 30-day readmission rate, including hospitals that have no score, sorted by readmission rate "
          "from lowest to highest.",
    "02": "Which measures are missing a score for more than half of Texas hospitals? Show the measure id, domain, "
          "name, number of hospitals with a score, total Texas hospitals and percent missing, most missing first.",
    "03": "For Texas hospitals, what is the average 'would definitely recommend' percentage and the average overall "
          "star rating for each hospital ownership type? Include the hospital count per group, only groups with "
          "at least 5 hospitals, highest recommend percentage first.",
    "04": "Rank Houston-area hospitals by their heart failure 30-day readmission rate within each county, "
          "where rank 1 is the lowest rate. Show county, rank, hospital and rate.",
    "05": "For every Texas hospital with a pneumonia 30-day readmission score, show its score, the Texas average, "
          "the difference from the Texas average, and the average for its county, sorted with the hospitals "
          "furthest below the Texas average first.",
    "06": "Across all US hospitals, what is each Houston-area hospital's national percentile on heart failure "
          "30-day mortality? Rank all hospitals nationally, then show only the Houston-area ones. Is a low "
          "percentile good or bad here?",
    "07": "For the percentage of patients who rated their hospital 9 or 10, compute each Texas hospital's change "
          "from its prior reporting period, and show the 10 biggest improvements and the 10 biggest declines.",
    "08": "Build a composite quality score for Texas hospitals: z-score the pneumonia 30-day readmission rate "
          "(flip the sign so higher is better), the percent who would definitely recommend the hospital, and "
          "the sepsis care bundle percentage across Texas hospitals, then average the three z-scores. Show the "
          "top 10 and bottom 10 hospitals with all three z-scores.",
    "09": "Which Texas hospitals have a pneumonia 30-day readmission rate better than the Texas average (below it) "
          "but a 'would definitely recommend' percentage worse than the Texas average (below it)? Show the "
          "hospital, county, both scores and both averages.",
    "10": "For each Texas county, show the number of hospitals, the number with a pneumonia 30-day readmission "
          "score, the simple mean readmission score and the denominator-weighted mean readmission score, sorted "
          "by weighted mean.",
    "11": "For each Houston-area hospital, show in one row its pneumonia readmission rate, heart failure mortality "
          "rate, central-line infection ratio, sepsis care bundle percentage, would-recommend percentage and "
          "HCAHPS summary star rating, sorted by would-recommend percentage, highest first.",
    "12": "For the pneumonia readmission rate, heart failure mortality rate, central-line infection ratio, sepsis "
          "bundle percentage, would-recommend percentage and HCAHPS summary star rating, what share of Texas "
          "hospitals beat the national average (computed over all states), taking into account whether higher "
          "or lower is better? Show measure, number of Texas hospitals, number beating national and the share.",
}


def truth_result(num: str):
    path = next((ROOT / "sql").glob(f"{num}_*.sql"))
    text = "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                     if not l.strip().upper().startswith("SET SEARCH_PATH"))
    return run_sql(text)


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _key(v) -> str:
    return str(v).strip().casefold()


def _verdict(matched: int, total: int) -> str:
    return "match" if matched == total else ("partial" if matched / total >= 0.5 else "miss")


def compare(truth, gen_rows, tolerant: bool = False) -> tuple[str, str]:
    """Return (verdict, note).

    Strict (the rule of record): key = first text value of the truth row; numbers equal after rounding to 2 dp.
    Tolerant (diagnostic only): any text value of the truth row may serve as key, and numbers may differ by 0.051
    (the truth queries round some columns to 1 dp in SQL, and a generated query that rounds differently is not wrong).
    """
    if truth.row_count == 0:
        return ("match", "truth empty and generated empty") if not gen_rows else ("miss", "truth empty, generated not")
    if not gen_rows:
        return "miss", "no generated rows"
    gen = [({_key(v) for v in r if isinstance(v, str)}, [float(v) for v in r if _is_num(v)]) for r in gen_rows]
    tol = 0.051 if tolerant else 0.0

    def has(nums: list[float], n: float) -> bool:
        return any(abs(round(g, 2) - round(n, 2)) <= tol for g in nums)

    matched = 0
    for r in truth.rows:
        texts = [_key(v) for v in r if isinstance(v, str)]
        keys = texts if tolerant else texts[:1]
        nums = [float(v) for v in r if _is_num(v)]
        cands = [g_nums for g_texts, g_nums in gen if (not keys or any(k in g_texts for k in keys))]
        if any(all(has(c, n) for n in nums) for c in cands):
            matched += 1
    return _verdict(matched, truth.row_count), f"{matched}/{truth.row_count} truth rows matched; generated {len(gen_rows)} rows"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", default="run")
    ap.add_argument("--plan", default=pipeline.PLAN_PROMPT)
    ap.add_argument("--schema", default=pipeline.SCHEMA_PROMPT)
    ap.add_argument("--answer", default=pipeline.ANSWER_PROMPT)
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args(argv)
    pipeline.PLAN_PROMPT, pipeline.SCHEMA_PROMPT, pipeline.ANSWER_PROMPT = args.plan, args.schema, args.answer

    llm, emb = OpenAILLM(), OpenAIEmbedder()
    results = []
    for num, question in QUESTIONS.items():
        if args.only and num not in args.only:
            continue
        truth = truth_result(num)
        try:
            a = pipeline.ask(question, llm=llm, embedder=emb)
            # the pipeline shows 50 rows; re-run its guarded SQL for the full capped result to compare
            gen_rows = run_sql(a.sql).rows if a.sql and not a.refused else []
            verdict, note = compare(truth, gen_rows)
            tol_verdict, tol_note = compare(truth, gen_rows, tolerant=True)
            rec = dict(refused=a.refused, sql_error=a.sql_error, repaired=a.repaired, route=a.route, sql=a.sql,
                       refusal_reason=a.refusal_reason, cost_usd=a.total_cost_usd,
                       latency_ms=a.timings.get("total_ms"), tokens=a.total_input_tokens + a.total_output_tokens)
        except Exception as e:  # keep the sweep going; record the failure
            verdict, note = "miss", f"exception: {type(e).__name__}: {e}"[:200]
            tol_verdict, tol_note = "miss", note
            rec = dict(refused=False, sql_error=note, repaired=False, route=None, sql=None, refusal_reason=None,
                       cost_usd=0.0, latency_ms=None, tokens=0)
        results.append(dict(id=num, question=question, verdict=verdict, note=note,
                            tolerant_verdict=tol_verdict, tolerant_note=tol_note, truth_rows=truth.row_count, **rec))
        print(f"{num} {verdict:7} (tolerant {tol_verdict:7}) {note[:60]}", flush=True)

    score = {v: sum(r["verdict"] == v for r in results) for v in ("match", "partial", "miss")}
    tscore = {v: sum(r["tolerant_verdict"] == v for r in results) for v in ("match", "partial", "miss")}
    lat = [r["latency_ms"] for r in results if r["latency_ms"]]
    run = dict(label=args.label, utc=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               prompts=dict(plan=args.plan, schema=args.schema, answer=args.answer), score=score, tolerant_score=tscore,
               total_cost_usd=round(sum(r["cost_usd"] for r in results), 5),
               median_latency_ms=int(statistics.median(lat)) if lat else None, max_latency_ms=max(lat) if lat else None,
               results=results)
    out = ROOT / "evals" / "results" / f"parity_12_{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d}.json"
    out.parent.mkdir(exist_ok=True)
    runs = json.loads(out.read_text(encoding="utf-8"))["runs"] if out.exists() else []
    out.write_text(json.dumps({"runs": runs + [run]}, indent=2), encoding="utf-8")
    print(f"\n{args.label}: {score}  cost ${run['total_cost_usd']}  median {run['median_latency_ms']} ms  -> {out}")


if __name__ == "__main__":
    main()
