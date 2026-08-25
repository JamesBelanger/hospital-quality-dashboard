"""Run every exercise against Supabase, save sql/NN_name.sql with a result header, print peeks.
Usage: python sql/_run_all.py            (all)      python sql/_run_all.py 05 12   (subset by number)
"""
import sys, datetime, psycopg2
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "etl")); from load import db_url  # noqa: E402
TODAY = datetime.date.today().isoformat()
KEY6 = "('READM_30_PN','MORT_30_HF','HAI_1_SIR','SEP_1','H_RECMND_DY','H_STAR_RATING')"

EX = {
"02_sparse_measures_tx": (
 "Which measures are missing (NULL score) for >50% of Texas hospitals?",
 "Count distinct Texas hospitals with a non-null score per measure vs total Texas hospitals; LEFT JOIN so zero-coverage measures (Hybrid_HWR) appear.",
 """WITH tx AS (SELECT facility_id FROM hospitals WHERE is_texas),
cov AS (
  SELECT m.measure_id, m.domain, m.measure_name,
         count(DISTINCT v.facility_id) FILTER (WHERE v.score IS NOT NULL) AS hospitals_with_score,
         (SELECT count(*) FROM tx) AS hospitals_total
  FROM measures m
  LEFT JOIN measure_values v
         ON v.measure_id = m.measure_id AND v.domain = m.domain
        AND v.facility_id IN (SELECT facility_id FROM tx)
  GROUP BY 1, 2, 3)
SELECT measure_id, domain, left(measure_name, 60) AS measure_name, hospitals_with_score, hospitals_total,
       round(100.0 * (hospitals_total - hospitals_with_score) / hospitals_total, 1) AS pct_missing
FROM cov
WHERE (hospitals_total - hospitals_with_score)::numeric / hospitals_total > 0.5
ORDER BY pct_missing DESC, measure_id"""),

"03_recommend_vs_rating_by_ownership": (
 "Do patients recommend nonprofits more than for-profits? Avg 'would recommend' and avg star rating by ownership, Texas, groups >= 5 hospitals.",
 "hospitals (Texas) LEFT JOIN latest H_RECMND_DY; GROUP BY ownership with HAVING for the size floor.",
 """SELECT h.hospital_ownership,
       count(DISTINCT h.facility_id)   AS hospitals,
       round(avg(v.score), 1)          AS avg_recommend_pct,
       round(avg(h.overall_rating), 2) AS avg_star_rating
FROM hospitals h
LEFT JOIN v_tx_latest v ON v.facility_id = h.facility_id AND v.measure_id = 'H_RECMND_DY'
WHERE h.is_texas
GROUP BY 1
HAVING count(DISTINCT h.facility_id) >= 5
ORDER BY avg_recommend_pct DESC NULLS LAST"""),

"04_rank_within_county": (
 "Rank Houston-area hospitals by heart-failure readmission within each county (rank 1 = best).",
 "v_tx_latest filtered to READM_30_HF + is_houston_area; RANK() OVER (PARTITION BY county ORDER BY score).",
 """SELECT county,
       RANK() OVER (PARTITION BY county ORDER BY score) AS rank_in_county,
       facility_name,
       score AS readm_30_hf_pct
FROM v_tx_latest
WHERE measure_id = 'READM_30_HF' AND is_houston_area
ORDER BY county, rank_in_county"""),

"05_vs_state_average": (
 "Each Texas hospital's pneumonia readmission vs the Texas average and vs its county average - benchmarking without a benchmark table.",
 "Two window averages over the same filtered set: AVG() OVER () and AVG() OVER (PARTITION BY county).",
 """SELECT facility_name, county, score AS readm_30_pn_pct,
       round(avg(score) OVER (), 2)                            AS tx_avg,
       round(score - avg(score) OVER (), 2)                    AS diff_vs_tx,
       round(avg(score) OVER (PARTITION BY county), 2)         AS county_avg,
       round(score - avg(score) OVER (PARTITION BY county), 2) AS diff_vs_county
FROM v_tx_latest
WHERE measure_id = 'READM_30_PN'
ORDER BY diff_vs_tx"""),

"06_national_percentile": (
 "National percentile of each Houston-area hospital on heart-failure mortality (all states). Low percentile = low mortality = GOOD.",
 "Latest period per hospital from the full fact table (DISTINCT ON), PERCENT_RANK() over all scored hospitals, then filter to Houston.",
 """WITH latest AS (
  SELECT DISTINCT ON (facility_id) facility_id, score
  FROM measure_values
  WHERE measure_id = 'MORT_30_HF' AND score IS NOT NULL
  ORDER BY facility_id, period_end DESC),
ranked AS (
  SELECT facility_id, score, PERCENT_RANK() OVER (ORDER BY score) AS pct_rank FROM latest)
SELECT h.facility_name, h.county, r.score AS mort_30_hf_pct, round(r.pct_rank::numeric, 3) AS national_percentile
FROM ranked r JOIN hospitals h USING (facility_id)
WHERE h.is_houston_area
ORDER BY national_percentile"""),

"07_period_over_period": (
 "Change in 'rated 9-10' between reporting periods per Texas hospital (LAG). If the release has one period, the query still demonstrates the pattern.",
 "LAG(score) OVER (PARTITION BY facility_id ORDER BY period_end) on the full fact table; keep rows with a prior period.",
 """WITH s AS (
  SELECT v.facility_id, v.period_end, v.score,
         LAG(v.score) OVER (PARTITION BY v.facility_id ORDER BY v.period_end) AS prev_score
  FROM measure_values v JOIN hospitals h USING (facility_id)
  WHERE h.is_texas AND v.measure_id = 'H_HSP_RATING_9_10' AND v.score IS NOT NULL)
SELECT h.facility_name, s.period_end, s.score, s.prev_score, s.score - s.prev_score AS change
FROM s JOIN hospitals h USING (facility_id)
WHERE s.prev_score IS NOT NULL
ORDER BY change DESC"""),

"08_quality_composite": (
 "A 3-domain quality composite for Texas hospitals: z(readmission, sign-flipped) + z(recommend) + z(sepsis care), averaged. Top 10 and bottom 10.",
 "One CTE per domain computing a z-score with window AVG/STDDEV over Texas; final CTE joins the three; UNION of top/bottom slices.",
 """WITH readm AS (
  SELECT facility_id, -(score - avg(score) OVER ()) / NULLIF(stddev(score) OVER (), 0) AS z_readm
  FROM v_tx_latest WHERE measure_id = 'READM_30_PN'),
rec AS (
  SELECT facility_id, (score - avg(score) OVER ()) / NULLIF(stddev(score) OVER (), 0) AS z_recommend
  FROM v_tx_latest WHERE measure_id = 'H_RECMND_DY'),
sep AS (
  SELECT facility_id, (score - avg(score) OVER ()) / NULLIF(stddev(score) OVER (), 0) AS z_sepsis
  FROM v_tx_latest WHERE measure_id = 'SEP_1'),
comp AS (
  SELECT h.facility_name, h.county,
         round(z_readm::numeric, 2) AS z_readm, round(z_recommend::numeric, 2) AS z_recommend, round(z_sepsis::numeric, 2) AS z_sepsis,
         round(((z_readm + z_recommend + z_sepsis) / 3)::numeric, 2) AS composite
  FROM hospitals h JOIN readm USING (facility_id) JOIN rec USING (facility_id) JOIN sep USING (facility_id))
(SELECT 'top' AS bucket, * FROM comp ORDER BY composite DESC LIMIT 10)
UNION ALL
(SELECT 'bottom' AS bucket, * FROM comp ORDER BY composite ASC LIMIT 10)"""),

"09_mismatch_finder": (
 "Texas hospitals better than the state average on readmission but worse on patient experience - the clinically-good / experientially-weak quadrant.",
 "Two CTEs for the two measures, a CTE of their Texas averages, CROSS JOIN the averages into the comparison.",
 """WITH r AS (SELECT facility_id, score AS readm FROM v_tx_latest WHERE measure_id = 'READM_30_PN'),
     p AS (SELECT facility_id, score AS recommend FROM v_tx_latest WHERE measure_id = 'H_RECMND_DY'),
     a AS (SELECT (SELECT avg(readm) FROM r) AS avg_readm, (SELECT avg(recommend) FROM p) AS avg_recommend)
SELECT h.facility_name, h.county,
       r.readm, round(a.avg_readm, 2) AS tx_avg_readm,
       p.recommend, round(a.avg_recommend, 1) AS tx_avg_recommend
FROM hospitals h JOIN r USING (facility_id) JOIN p USING (facility_id) CROSS JOIN a
WHERE r.readm < a.avg_readm AND p.recommend < a.avg_recommend
ORDER BY r.readm"""),

"10_county_rollup": (
 "County roll-up for Texas: hospitals, hospitals with a readmission score, plain mean vs denominator-weighted mean (counties with >= 3 scored hospitals).",
 "Per-hospital CTE (LEFT JOIN so unscored hospitals count), then GROUP BY county; weighted mean = SUM(score*denominator)/SUM(denominator).",
 """WITH per AS (
  SELECT h.county, h.facility_id, v.score, v.denominator
  FROM hospitals h
  LEFT JOIN v_tx_latest v ON v.facility_id = h.facility_id AND v.measure_id = 'READM_30_PN'
  WHERE h.is_texas)
SELECT county,
       count(*)                                                         AS hospitals,
       count(score)                                                     AS with_score,
       round(avg(score), 2)                                             AS mean_readm,
       round(sum(score * denominator) / NULLIF(sum(denominator), 0), 2) AS weighted_mean_readm
FROM per
GROUP BY county
HAVING count(score) >= 3
ORDER BY weighted_mean_readm NULLS LAST"""),

"11_scorecard_pivot": (
 "One row per Houston-area hospital with six key measures as columns - the dashboard extract shape.",
 "Conditional aggregation: MAX(score) FILTER (WHERE measure_id = ...) over the long table, grouped by hospital.",
 """SELECT facility_name, county,
       max(score) FILTER (WHERE measure_id = 'READM_30_PN')   AS readm_pn,
       max(score) FILTER (WHERE measure_id = 'MORT_30_HF')    AS mort_hf,
       max(score) FILTER (WHERE measure_id = 'HAI_1_SIR')     AS hai_clabsi_sir,
       max(score) FILTER (WHERE measure_id = 'SEP_1')         AS sepsis_pct,
       max(score) FILTER (WHERE measure_id = 'H_RECMND_DY')   AS recommend_pct,
       max(score) FILTER (WHERE measure_id = 'H_STAR_RATING') AS star_rating
FROM v_tx_latest
WHERE is_houston_area
GROUP BY facility_name, county
ORDER BY recommend_pct DESC NULLS LAST"""),

"12_beat_national_share": (
 "For six key measures, what share of Texas hospitals beat the national average? Direction-aware via measures.higher_is_better.",
 "Latest value per (hospital, measure) from all states; national average per measure; direction from the measures dimension; count Texas hospitals on the good side.",
 f"""WITH latest AS (
  SELECT DISTINCT ON (facility_id, measure_id) facility_id, measure_id, score
  FROM measure_values
  WHERE measure_id IN {KEY6} AND score IS NOT NULL
  ORDER BY facility_id, measure_id, period_end DESC),
nat AS (SELECT measure_id, avg(score) AS national_avg FROM latest GROUP BY 1),
dirn AS (SELECT measure_id, bool_or(higher_is_better) AS higher_is_better FROM measures WHERE measure_id IN {KEY6} GROUP BY 1),
judged AS (
  SELECT l.measure_id, d.higher_is_better, n.national_avg, l.score,
         ((d.higher_is_better AND l.score > n.national_avg) OR (NOT d.higher_is_better AND l.score < n.national_avg)) AS beats
  FROM latest l JOIN hospitals h USING (facility_id) JOIN nat n USING (measure_id) JOIN dirn d USING (measure_id)
  WHERE h.is_texas)
SELECT measure_id, higher_is_better, round(national_avg, 2) AS national_avg,
       count(*) AS tx_hospitals,
       count(*) FILTER (WHERE beats) AS tx_beating_national,
       round(100.0 * count(*) FILTER (WHERE beats) / count(*), 1) AS share_pct
FROM judged
GROUP BY 1, 2, 3
ORDER BY share_pct DESC"""),
}


def main(only=None):
    with psycopg2.connect(db_url()) as c, c.cursor() as cur:
        cur.execute("SET search_path TO hq")
        for name, (q, approach, sql) in EX.items():
            if only and name[:2] not in only:
                continue
            cur.execute(sql); rows = cur.fetchall(); cols = [d[0] for d in cur.description]
            hdr = f"-- {name}.sql\n-- Q: {q}\n-- Approach: {approach}\n-- Result: {len(rows)} rows on {TODAY}.\nSET search_path TO hq;\n\n"
            (ROOT / "sql" / f"{name}.sql").write_text(hdr + sql + ";\n", encoding="utf-8")
            print(f"\n== {name}: {len(rows)} rows ==")
            print("   " + " | ".join(cols[:6]))
            for r in rows[:4]:
                print("   " + " | ".join(str(x)[:38] for x in r[:6]))


if __name__ == "__main__":
    main(set(sys.argv[1:]) or None)
