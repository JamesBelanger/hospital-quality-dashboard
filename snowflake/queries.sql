-- queries.sql — four analyses on Snowflake, mirroring the PostgreSQL exercises.
-- Snowflake idioms used on purpose: QUALIFY ROW_NUMBER() (instead of DISTINCT ON),
-- COUNT_IF / AVG(IFF(...)) (instead of FILTER (WHERE)).

USE DATABASE HQ; USE SCHEMA PUBLIC; USE WAREHOUSE HQ_WH;

-- Q1 — National percentile of each Houston-area hospital on heart-failure mortality.
-- Low percentile = low mortality = good. (Postgres original: 06_national_percentile.sql)
WITH latest AS (
    SELECT facility_id, score
    FROM measure_values
    WHERE measure_id = 'MORT_30_HF' AND score IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY facility_id ORDER BY period_end DESC) = 1
),
ranked AS (
    SELECT facility_id, score,
           PERCENT_RANK() OVER (ORDER BY score) AS pct_rank
    FROM latest
)
SELECT h.facility_name, h.county, r.score AS mort_30_hf_pct,
       ROUND(r.pct_rank, 3) AS national_percentile
FROM ranked r
JOIN hospitals h USING (facility_id)
WHERE h.is_houston_area
ORDER BY national_percentile;                      -- expect ~32 rows

-- Q2 — Texas vs national, per key measure: share of Texas hospitals beating the national average.
WITH latest AS (
    SELECT facility_id, measure_id, score
    FROM measure_values
    WHERE score IS NOT NULL
      AND measure_id IN ('READM_30_PN','READM_30_HF','MORT_30_HF','MORT_30_PN','HAI_1_SIR',
                         'HAI_2_SIR','SEP_1','OP_22','H_RECMND_DY','H_HSP_RATING_9_10','H_STAR_RATING')
    QUALIFY ROW_NUMBER() OVER (PARTITION BY facility_id, measure_id ORDER BY period_end DESC) = 1
),
w AS (
    SELECT l.*, h.is_texas,
           AVG(l.score) OVER (PARTITION BY l.measure_id) AS national_avg
    FROM latest l JOIN hospitals h USING (facility_id)
),
d AS (SELECT measure_id, MAX(IFF(higher_is_better, 1, 0)) = 1 AS hib FROM measures GROUP BY measure_id)
SELECT w.measure_id,
       ROUND(AVG(IFF(w.is_texas, w.score, NULL)), 2)  AS tx_avg,
       ROUND(AVG(w.score), 2)                          AS national_avg,
       COUNT_IF(w.is_texas)                            AS tx_hospitals,
       ROUND(100 * COUNT_IF(w.is_texas AND ((d.hib AND w.score > w.national_avg)
                                        OR (NOT d.hib AND w.score < w.national_avg)))
             / NULLIF(COUNT_IF(w.is_texas), 0), 1)     AS tx_share_beating_pct
FROM w JOIN d USING (measure_id)
GROUP BY w.measure_id
ORDER BY tx_share_beating_pct DESC;                   -- expect 11 rows

-- Q3 — Houston scorecard pivot: one row per Houston hospital, key measures as columns.
WITH latest AS (
    SELECT facility_id, measure_id, score
    FROM measure_values
    WHERE score IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (PARTITION BY facility_id, measure_id ORDER BY period_end DESC) = 1
)
SELECT h.facility_name, h.county,
       MAX(IFF(l.measure_id = 'READM_30_PN',  l.score, NULL)) AS pneumonia_readmit_pct,
       MAX(IFF(l.measure_id = 'MORT_30_HF',   l.score, NULL)) AS hf_mortality_pct,
       MAX(IFF(l.measure_id = 'HAI_1_SIR',    l.score, NULL)) AS clabsi_sir,
       MAX(IFF(l.measure_id = 'H_RECMND_DY',  l.score, NULL)) AS would_recommend_pct
FROM hospitals h
JOIN latest l USING (facility_id)
WHERE h.is_houston_area
GROUP BY h.facility_name, h.county
HAVING hf_mortality_pct IS NOT NULL
ORDER BY hf_mortality_pct
LIMIT 20;                                             -- expect 20 rows

-- Q4 — Data-quality: measures missing for more than half of Texas hospitals.
WITH tx AS (SELECT COUNT(*) AS n FROM hospitals WHERE is_texas),
cov AS (
    SELECT mv.measure_id,
           COUNT(DISTINCT IFF(h.is_texas AND mv.score IS NOT NULL, mv.facility_id, NULL)) AS tx_reporting
    FROM measure_values mv JOIN hospitals h USING (facility_id)
    GROUP BY mv.measure_id
)
SELECT c.measure_id, c.tx_reporting, t.n AS tx_total,
       ROUND(100 * (1 - c.tx_reporting / t.n), 1) AS pct_missing
FROM cov c CROSS JOIN tx t
WHERE c.tx_reporting < t.n / 2
ORDER BY pct_missing DESC;                            -- expect ~90 rows
