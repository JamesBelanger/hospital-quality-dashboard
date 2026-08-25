-- DAY 12 (2026-09-06) - card for sql/12_beat_national_share.sql
-- STEP 1: paste this whole file into the Supabase SQL Editor and Run. Note the row count.
-- STEP 2 (the tweak): change   'H_STAR_RATING')   to   'H_STAR_RATING','OP_22')
--          why: add ED walk-outs (OP_22) to the six measures - does Texas beat national there?
-- STEP 3: Run again, then fill in today's row in sql/LOG.md.

-- 12_beat_national_share.sql
-- Q: For six key measures, what share of Texas hospitals beat the national average? Direction-aware via measures.higher_is_better.
-- Approach: Latest value per (hospital, measure) from all states; national average per measure; direction from the measures dimension; count Texas hospitals on the good side.
-- Result: 6 rows on 2026-08-25.
SET search_path TO hq;

WITH latest AS (
  SELECT DISTINCT ON (facility_id, measure_id) facility_id, measure_id, score
  FROM measure_values
  WHERE measure_id IN ('READM_30_PN','MORT_30_HF','HAI_1_SIR','SEP_1','H_RECMND_DY','H_STAR_RATING') AND score IS NOT NULL
  ORDER BY facility_id, measure_id, period_end DESC),
nat AS (SELECT measure_id, avg(score) AS national_avg FROM latest GROUP BY 1),
dirn AS (SELECT measure_id, bool_or(higher_is_better) AS higher_is_better FROM measures WHERE measure_id IN ('READM_30_PN','MORT_30_HF','HAI_1_SIR','SEP_1','H_RECMND_DY','H_STAR_RATING') GROUP BY 1),
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
ORDER BY share_pct DESC;
