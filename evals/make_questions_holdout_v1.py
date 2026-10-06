"""Build and verify the HOLDOUT question set  ->  evals/questions_holdout_v1.jsonl

    .venv/Scripts/python.exe evals/make_questions_holdout_v1.py          # needs HQ_READER_URL in .env

Written AFTER retrieval and the planner prompt were frozen (see Architecture notes in evals/README.md) and
without running retrieval or the pipeline on any of these questions. Document questions were chosen by
reading the seven documents in docs_index/chunks.jsonl, one chunk at a time, not by searching for what
retrieves well. Same schema as questions_v1.jsonl, with split "holdout".

Contents: 15 definition (hdef-01..15), 3 definition_unanswerable (hdefx-01..03), 8 numeric (hnum-01..08;
3 easy, 3 medium, 2 hard). All checks of make_questions_v1.py run here too (its verifiers are reused
unchanged; its schema check only knows the splits dev/test, so the holdout questions are presented to it
with split "test" and the real split is restored before writing). Extra checks:
  * counts and id ranges; difficulty mix of the numeric questions; >= 2 numeric questions name a county or
    city; >= 2 are national
  * no definition question shares an expected chunk with a v1 definition question, and none is textually
    close to any v1 question (difflib ratio < 0.6)
  * every answer_point evidence quote appears in the expected chunks and in no other chunk of the library
    (so the expected chunk is the only place the fact is stated)
  * unanswerable question patterns match nothing in the library (checked by the reused verifier)
Nothing is written unless every check passes.
"""
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import make_questions_v1 as V1  # noqa: E402  (its verifiers and helpers; not modified)
from evals.make_questions_v1 import DICT, HCF, HST, HWM, HWR, PSI, SEP, load_chunks, norm  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent / "questions_holdout_v1.jsonl"
V1_PATH = Path(__file__).resolve().parent / "questions_v1.jsonl"


# --------------------------------------------------------------------------------------
# Numeric
# --------------------------------------------------------------------------------------
def N(id, difficulty, question, truth_sql, key, values, measure_ids, scope, notes=None):
    d = dict(id=id, type="numeric", split="holdout", difficulty=difficulty, question=question,
             author="claude", truth_sql=V1.sql(truth_sql), key_column=key, value_columns=values,
             measure_ids=measure_ids)
    if notes:
        d["notes"] = notes
    SCOPE[id] = scope
    return d


SCOPE: dict[str, str] = {}  # id -> "national" | "place" | "state"  (design bookkeeping, not written to the file)


def _mv(alias, measure):
    return f"JOIN measure_values {alias} ON {alias}.facility_id = h.facility_id AND {alias}.measure_id = '{measure}'"


NUMERIC = [
    N("hnum-01", "easy", "Across the whole country, how many hospitals earned the top overall rating of 5 stars?",
      "SELECT count(*) AS five_star_hospitals FROM hospitals WHERE overall_rating = 5",
      None, ["five_star_hospitals"], [], "national"),
    N("hnum-02", "easy", "How many hospitals does the data list for Cook County, Illinois?",
      "SELECT count(*) AS cook_county_hospitals FROM hospitals WHERE state = 'IL' AND county = 'COOK'",
      None, ["cook_county_hospitals"], [], "place"),
    N("hnum-03", "easy",
      "Nationwide, how many hospitals report a pneumonia readmission rate under 15 percent within 30 days?",
      "SELECT count(DISTINCT facility_id) AS hospitals_below_15 FROM measure_values "
      "WHERE measure_id = 'READM_30_PN' AND score < 15",
      None, ["hospitals_below_15"], ["READM_30_PN"], "national"),
    N("hnum-04", "medium",
      "Which five U.S. states or territories have the highest percentage of their rated hospitals at 5 stars, counting "
      "only those with at least 25 hospitals that have an overall star rating? Give the state code, the number of rated "
      "hospitals, the number with 5 stars and the percentage (1 decimal), highest first. Break ties by state abbreviation.",
      """
      SELECT state, count(*) AS rated_hospitals,
             count(*) FILTER (WHERE overall_rating = 5) AS five_star_hospitals,
             round(100.0 * count(*) FILTER (WHERE overall_rating = 5) / count(*), 1) AS five_star_pct
      FROM hospitals
      WHERE overall_rating IS NOT NULL
      GROUP BY state
      HAVING count(*) >= 25
      ORDER BY count(*) FILTER (WHERE overall_rating = 5)::numeric / count(*) DESC, state
      LIMIT 5
      """,
      "state", ["rated_hospitals", "five_star_hospitals", "five_star_pct"], [], "national"),
    N("hnum-05", "medium",
      "List the hospitals in Philadelphia, Pennsylvania that have a 30-day heart failure readmission rate, with the rate "
      "and the number of eligible discharges behind it, lowest rate first. Break ties by hospital name.",
      f"""
      SELECT h.facility_name, v.score AS readm_30_hf_pct, v.denominator AS eligible_discharges
      FROM hospitals h {_mv('v', 'READM_30_HF')}
      WHERE h.state = 'PA' AND h.city = 'PHILADELPHIA' AND v.score IS NOT NULL
      ORDER BY v.score, h.facility_name, h.facility_id
      """,
      "facility_name", ["readm_30_hf_pct", "eligible_discharges"], ["READM_30_HF"], "place"),
    N("hnum-06", "medium",
      "In Florida, what is the average 30-day heart failure death rate by hospital ownership type? Include only ownership "
      "types with at least 5 hospitals that have the rate, and show the number of hospitals and the average (2 decimals), "
      "highest average first. Break ties by ownership type.",
      f"""
      SELECT h.hospital_ownership, count(*) AS hospitals, round(avg(v.score), 2) AS avg_mort_30_hf_pct
      FROM hospitals h {_mv('v', 'MORT_30_HF')}
      WHERE h.state = 'FL' AND v.score IS NOT NULL
      GROUP BY h.hospital_ownership
      HAVING count(*) >= 5
      ORDER BY avg(v.score) DESC, h.hospital_ownership
      """,
      "hospital_ownership", ["hospitals", "avg_mort_30_hf_pct"], ["MORT_30_HF"], "state"),
    N("hnum-07", "hard",
      "In Los Angeles County, California, which 10 hospitals have the highest 30-day pneumonia death rate? Show the "
      "hospital, its city, its rate, the national average rate (average over all U.S. hospitals with that rate, 2 decimals) "
      "and how far the hospital's rate is above the national average (2 decimals), highest rate first. Break ties by hospital name.",
      f"""
      WITH nat AS (
        SELECT avg(score) AS national_avg FROM measure_values
        WHERE measure_id = 'MORT_30_PN' AND score IS NOT NULL)
      SELECT h.facility_name, h.city, v.score AS mort_30_pn_pct,
             round(nat.national_avg, 2) AS national_avg_pct,
             round(v.score - nat.national_avg, 2) AS diff_from_national
      FROM hospitals h {_mv('v', 'MORT_30_PN')}
      CROSS JOIN nat
      WHERE h.state = 'CA' AND h.county = 'LOS ANGELES' AND v.score IS NOT NULL
      ORDER BY v.score DESC, h.facility_name, h.facility_id
      LIMIT 10
      """,
      "facility_name", ["mort_30_pn_pct", "national_avg_pct", "diff_from_national"], ["MORT_30_PN"], "place"),
    N("hnum-08", "hard",
      "Among states and territories with at least 30 hospitals that report the sepsis care score (appropriate care for severe "
      "sepsis and septic shock), which 10 have an average score furthest below the national average (average over all U.S. "
      "hospitals with a score)? Give the state code, the number of hospitals, the state average, the national average and the "
      "difference (state minus national), all averages and the difference to 1 decimal, most below first. Break ties by state abbreviation.",
      f"""
      WITH nat AS (
        SELECT avg(score) AS national_avg FROM measure_values
        WHERE measure_id = 'SEP_1' AND score IS NOT NULL),
      st AS (
        SELECT h.state, count(*) AS hospitals, avg(v.score) AS state_avg
        FROM hospitals h {_mv('v', 'SEP_1')}
        WHERE v.score IS NOT NULL
        GROUP BY h.state
        HAVING count(*) >= 30)
      SELECT st.state, st.hospitals, round(st.state_avg, 1) AS state_avg_pct,
             round(nat.national_avg, 1) AS national_avg_pct,
             round(st.state_avg - nat.national_avg, 1) AS diff_from_national
      FROM st CROSS JOIN nat
      ORDER BY st.state_avg - nat.national_avg, st.state
      LIMIT 10
      """,
      "state", ["hospitals", "state_avg_pct", "national_avg_pct", "diff_from_national"], ["SEP_1"], "national"),
]


# --------------------------------------------------------------------------------------
# Definition (15) and definition_unanswerable (3)
# --------------------------------------------------------------------------------------
def D(id, difficulty, question, chunks, points):
    return dict(id=id, type="definition", split="holdout", difficulty=difficulty, question=question,
                author="claude", expected_chunk_ids=chunks,
                answer_points=[{"point": p, "evidence": e} for p, e in points])


DEFINITIONS = [
    D("hdef-01", "medium",
      "In hospital value-based purchasing, how much of the Total Performance Score comes from the patient-experience "
      "domain that is based on HCAHPS, and which two scores make up that domain's score?",
      [f"{HCF}:6"],
      [("The patient-experience (Person and Community Engagement) domain accounts for 25% of the Total Performance Score",
        "which accounts for 25% of the Hospital VBP Total Performance Score"),
       ("One part is the HCAHPS Base Score, worth 0 to 80 points", "HCAHPS Base Score (0–80 points)"),
       ("The other part is the HCAHPS Consistency Score, worth 0 to 20 points", "HCAHPS Consistency Score (0–20 points)")]),
    D("hdef-02", "easy",
      "How many publicly reported measures does the updated HCAHPS survey produce, and how many of them are composite "
      "(multi-item) versus single-item measures?",
      [f"{HCF}:2"],
      [("The updated survey produces 11 publicly reported measures", "produces 11 publicly reported measures"),
       ("7 of them are composite (multi-item) measures", "7 composite (multi-item) measures"),
       ("4 of them are single-item measures", "4 single-item measures")]),
    D("hdef-03", "medium",
      "How are the four quarterly HCAHPS linear scores combined into one score for the reporting period, and what "
      "determines the weight of each quarter?",
      [f"{HST}:10", f"{HST}:12"],
      [("The four quarterly scores are averaged with weights proportional to the number of eligible patients each quarter",
        "weighted proportionately to the number of eligible patients seen by the hospital in each quarter"),
       ("A quarter's weight is its eligible discharge size divided by the total eligible discharge size for the four quarters",
        "that quarter's eligible discharge size divided by the total eligible discharge size for the four quarters")]),
    D("hdef-04", "medium",
      "For the HCAHPS star ratings, which survey modes are adjusted for, where does the mode adjustment come from, and on "
      "what scale is it applied?",
      [f"{HST}:9"],
      [("Scores are adjusted for the mode of survey administration: mail, telephone, mixed mode or Interactive Voice Response",
        "(mail, telephone, mixed mode or Interactive Voice Response)"),
       ("The adjustments were derived from a large-scale randomized mode experiment",
        "a large-scale, randomized mode experiment"),
       ("They are applied to the rescaled 0-100 linear mean score for each measure",
        "applied on the rescaled (0-100) linear mean score for each measure")]),
    D("hdef-05", "medium",
      "What kind of data does the BPCI Advanced version of the severe sepsis and septic shock management bundle measure "
      "use, what calendar period does it cover, and what decides the year a claim belongs to?",
      [f"{SEP}:8"],
      [("It uses chart-abstracted data that BPCI Advanced participants already submit for the Hospital IQR Program",
        "chart-abstracted data which BPCI Advanced Participants are already submitting for the Hospital IQR Program"),
       ("The model measures January 1 through December 31", "the Model uses January 1 through December 31 for measure calculation"),
       ("The date of discharge on the index admission determines the calendar year of the claim",
        "The date of discharge on the index admission will determine the calendar year in which the claim belongs")]),
    D("hdef-06", "easy",
      "How many Patient Safety Indicators did AHRQ develop, how many of them are provider-level indicators, and what kind "
      "of events do they highlight?",
      [f"{PSI}:1"],
      [("There are 26 Patient Safety Indicator measures", "comprised of 26 measures"),
       ("18 of them are provider-level indicators", "including 18 provider-level indicators"),
       ("They highlight safety-related adverse events in hospitals after operations, procedures and childbirth",
        "safety-related adverse events occurring in hospitals following operations, procedures, and childbirth")]),
    D("hdef-07", "medium",
      "Under the Hospital-Acquired Condition Reduction Program, which hospitals have their Medicare payments reduced, by how "
      "much, and how is the Total HAC Score formed?",
      [f"{DICT}:13"],
      [("Hospitals with a Total HAC Score above the 75th percentile of the distribution are subject to the reduction",
        "above the 75th percentile of the Total HAC Score distribution"),
       ("The payment reduction is 1 percent", "1-percent payment reduction"),
       ("The Total HAC Score is the equally weighted average of the individual measure scores",
        "The Total HAC Score is the equally weighted average of individual measure scores")]),
    D("hdef-08", "medium",
      "How many complications does the hip and knee replacement complication measure look for, and why does CMS limit them "
      "to specified time periods after admission?",
      [f"{DICT}:8"],
      [("The measure estimates the likelihood that at least 1 of 8 complications occurs",
        "at least 1 of 8 complications occurs within a specified time period"),
       ("Longer periods could be affected by factors outside the hospital's control such as other illnesses, patient behavior or care after discharge",
        "complications over a longer period may be impacted by factors outside the hospitals' control")]),
    D("hdef-09", "medium",
      "What period of care does the Medicare spending per beneficiary measure cover, which payments does it include, and how "
      "are those payments adjusted?",
      [f"{DICT}:22"],
      [("It covers Medicare Part A and Part B payments for services provided to a beneficiary",
        "Medicare Part A and Part B payments for services provided to a Medicare beneficiary"),
       ("The episode spans from three days before an inpatient admission through 30 days after discharge",
        "from three days prior to an inpatient hospital admission through 30 days after discharge"),
       ("The payments are price-standardized and risk-adjusted", "price-standardized and risk-adjusted")]),
    D("hdef-10", "easy",
      "Which health system supplied the data used to develop the hybrid hospital-wide readmission measure, and what range of "
      "admission dates did the datasets cover?",
      [f"{HWR}:6", f"{HWR}:7"],
      [("The data came from Kaiser Permanente of Northern California (KPNC)",
        "provided by Kaiser Permanente of Northern California (KPNC)"),
       ("The datasets cover admissions between January 1, 2009 and January 31, 2013",
        "between January 1, 2009 and January 31, 2013")]),
    D("hdef-11", "medium",
      "Which EHR systems were included in the feasibility testing for the hybrid hospital-wide readmission measure, and "
      "roughly what share of Meaningful Use hospitals used them?",
      [f"{HWR}:104"],
      [("Epic, Cerner, Meditech and Allscripts were the four EHR systems included in testing",
        "Epic, Cerner, Meditech, and Allscripts"),
       ("Together they are used in approximately 50% of hospitals attesting for Meaningful Use in 2013",
        "approximately 50% of hospitals attesting for Meaningful Use in 2013")]),
    D("hdef-12", "hard",
      "What three principles does the planned readmission algorithm use to decide whether a readmission counts as planned?",
      [f"{HWR}:14"],
      [("A few specific types of care are always considered planned, such as transplant surgery, maintenance chemotherapy or rehabilitation",
        "A few specific, limited types of care are always considered planned"),
       ("Otherwise a planned readmission is a non-acute readmission for a scheduled procedure",
        "a planned readmission is defined as a non-acute readmission for a scheduled procedure"),
       ("Admissions for acute illness or for complications of care are never planned",
        "Admissions for acute illness or for complications of care are never planned")]),
    D("hdef-13", "medium",
      "According to the rationale for the hospital-wide mortality measure, roughly how many patients die each year from "
      "preventable harm in hospitals, and why do existing condition-specific mortality measures fall short?",
      [f"{HWM}:10", f"{HWM}:15"],
      [("More than 400,000 patients die each year from preventable harm in hospitals",
        "more than 400,000 patients die each year from preventable harm in hospitals"),
       ("Condition-specific measures do not measure a hospital's broader performance",
        "allow for measurement of a hospital's broader performance"),
       ("They also do not meaningfully capture performance for smaller-volume hospitals",
        "meaningfully capture performance for smaller volume hospitals")]),
    D("hdef-14", "medium",
      "What range of annual cost does the hospital-wide mortality report give for potentially preventable deaths, and what "
      "assumption about lost years of life does it use?",
      [f"{HWM}:16"],
      [("The annual direct and indirect cost could be as much as $73.5 to $735 billion", "$73.5 to $735 billion"),
       ("It assumes an average of ten lost years of life per death", "an average of ten lost years of life per death"),
       ("Each lost year is valued at $75,000", "valued at $75,000 per year")]),
    D("hdef-15", "hard",
      "For the original (ICD-9) development of the hospital-wide mortality measure, which Medicare beneficiaries and "
      "admission period make up the claims-only development dataset, and what admission dates does the clinical hybrid "
      "development dataset cover?",
      [f"{HWM}:27"],
      [("The claims-only development dataset covers fee-for-service Medicare beneficiaries aged 65 and older hospitalized from July 1, 2014 to June 30, 2015",
        "hospitalized from July 1, 2014"),
       ("The clinical hybrid development dataset has admission dates from January 1, 2009 to June 30, 2015",
        "admission dates from January 1, 2009")]),
]


def X(id, question, searched, why):
    return dict(id=id, type="definition_unanswerable", split="holdout", difficulty="hard", question=question,
                author="claude", expected="refuse", why=why, absent_patterns=searched)


UNANSWERABLE = [
    X("hdefx-01", "How much does it cost a hospital to hire an approved vendor to administer the HCAHPS survey?",
      [r"\bvendors?\b[^.]{0,80}(cost|fee|price|\$)", r"(cost|fee|price|\$)[^.]{0,80}\bvendors?\b", r"cost[^.]{0,40}(administer|survey)"],
      "The fact sheet says hospitals may use an approved survey vendor or self-administer, but no document states what a vendor costs."),
    X("hdefx-02", "How many acute care hospitals are currently enrolled in the BPCI Advanced Model?",
      [r"(participating|participants?|enrolled)[^.]{0,60}\b\d[\d,]*\b[^.]{0,30}(hospitals|participants)",
       r"\b\d[\d,]* (hospitals|participants)[^.]{0,40}(BPCI|participat|enroll)"],
      "The BPCI fact sheets describe the measures used in the model but never say how many hospitals take part."),
    X("hdefx-03", "What minimum Total Performance Score must a hospital reach to avoid a payment reduction under Hospital Value-Based Purchasing?",
      [r"(cut-?off|threshold|minimum)[^.]{0,80}(total performance score|TPS)", r"(total performance score|TPS)[^.]{0,120}(cut-?off|threshold|minimum|below)",
       r"avoid[^.]{0,60}(reduction|penalt)"],
      "The data dictionary and HCAHPS fact sheet describe how the Total Performance Score is built and that payments are adjusted, "
      "but no document states a score needed to avoid a reduction."),
]

ALL = NUMERIC + DEFINITIONS + UNANSWERABLE

EXPECTED = {"numeric": 8, "definition": 15, "definition_unanswerable": 3}


# --------------------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------------------
def extra_checks(questions: list, fails: list) -> None:
    ids = [q["id"] for q in questions]
    want = ([f"hnum-{i:02d}" for i in range(1, 9)] + [f"hdef-{i:02d}" for i in range(1, 16)]
            + [f"hdefx-{i:02d}" for i in range(1, 4)])
    if sorted(ids) != sorted(want):
        fails.append(f"ids differ from the design: {sorted(set(ids) ^ set(want))}")
    for t, n in EXPECTED.items():
        got = sum(1 for q in questions if q["type"] == t)
        if got != n:
            fails.append(f"count: {t} = {got}, expected {n}")
    mix = {d: sum(1 for q in questions if q["type"] == "numeric" and q["difficulty"] == d) for d in ("easy", "medium", "hard")}
    if mix != {"easy": 3, "medium": 3, "hard": 2}:
        fails.append(f"numeric difficulty mix {mix}, expected 3/3/2")
    scopes = [SCOPE[q["id"]] for q in questions if q["type"] == "numeric"]
    if scopes.count("place") < 2:
        fails.append("fewer than 2 numeric questions name a county or city")
    if scopes.count("national") < 2:
        fails.append("fewer than 2 national numeric questions")

    v1 = [json.loads(l) for l in V1_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    v1_chunks = {c for q in v1 if q["type"] == "definition" for c in q["expected_chunk_ids"]}
    v1_text = [q["question"] for q in v1]
    for q in questions:
        if q["type"] == "definition":
            shared = set(q["expected_chunk_ids"]) & v1_chunks
            if shared:
                fails.append(f"{q['id']}: expected chunk(s) {sorted(shared)} are also expected by a v1 definition question")
        for t in v1_text:
            if q["type"] == "numeric":
                break  # short numeric questions share boilerplate wording; their SQL and scope are what differ
            r = difflib.SequenceMatcher(None, norm(q["question"]), norm(t)).ratio()
            if r >= 0.6:
                fails.append(f"{q['id']}: too close to a v1 question (ratio {r:.2f}): {t[:70]!r}")

    # evidence must be stated only in the expected chunks (and in at least one of them)
    chunks = load_chunks()
    for q in questions:
        if q["type"] != "definition":
            continue
        for p in q["answer_points"]:
            ev = norm(p["evidence"])
            holders = [cid for cid, c in chunks.items() if ev in norm(c["text"])]
            outside = [h for h in holders if h not in q["expected_chunk_ids"]]
            if outside:
                fails.append(f"{q['id']}: evidence {p['evidence'][:50]!r} also appears in {outside[:3]}")
        if not 2 <= len(q["answer_points"]) <= 3:
            fails.append(f"{q['id']}: needs 2 or 3 answer_points")


def main() -> int:
    shadow = []
    for q in ALL:
        q = json.loads(json.dumps(q))
        q["split"] = "test"  # make_questions_v1's schema check only knows dev/test
        shadow.append(q)
    checked, fails = V1.verify_all(shadow, check_counts=False)
    for q in checked:
        q["split"] = "holdout"
    extra_checks(checked, fails)
    for f in fails:
        print("FAIL", f)
    if fails:
        print(f"\n{len(fails)} failure(s); nothing written.")
        return 1
    OUT_PATH.write_text("".join(json.dumps(q, ensure_ascii=True) + "\n" for q in checked), encoding="utf-8", newline="\n")
    by_type = {}
    for q in checked:
        by_type[q["type"]] = by_type.get(q["type"], 0) + 1
    print(f"OK: wrote {len(checked)} questions to {OUT_PATH}\n  by type: {by_type}")
    for q in checked:
        if q["type"] == "numeric":
            print(f"  {q['id']}: {q['expected_row_count']} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
