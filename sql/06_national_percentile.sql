-- 06_national_percentile.sql
-- Q: National percentile of each Houston-area hospital on heart-failure mortality (all states). Low percentile = low mortality = GOOD.
-- Approach: Latest period per hospital from the full fact table (DISTINCT ON), PERCENT_RANK() over all scored hospitals, then filter to Houston.
-- Result: 32 rows on 2026-08-25.
SET search_path TO hq;

WITH latest AS (
  SELECT DISTINCT ON (facility_id) facility_id, score
  FROM measure_values
  WHERE measure_id = 'MORT_30_HF' AND score IS NOT NULL
  ORDER BY facility_id, period_end DESC),
ranked AS (
  SELECT facility_id, score, PERCENT_RANK() OVER (ORDER BY score) AS pct_rank FROM latest)
SELECT h.facility_name, h.county, r.score AS mort_30_hf_pct, round(r.pct_rank::numeric, 3) AS national_percentile
FROM ranked r JOIN hospitals h USING (facility_id)
WHERE h.is_houston_area
ORDER BY national_percentile;
