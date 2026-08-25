-- DAY 07 (2026-09-01) - card for sql/07_period_over_period.sql
-- STEP 1: paste this whole file into the Supabase SQL Editor and Run. Note the row count.
-- STEP 2 (the tweak): change   'H_HSP_RATING_9_10'   to   'H_RECMND_DY'
--          why: try 'would recommend'. Still 0 rows (one period this release) - the point is you know why. Say so in the log.
-- STEP 3: Run again, then fill in today's row in sql/LOG.md.

-- 07_period_over_period.sql
-- Q: Change in 'rated 9-10' between reporting periods per Texas hospital (LAG). If the release has one period, the query still demonstrates the pattern.
-- Approach: LAG(score) OVER (PARTITION BY facility_id ORDER BY period_end) on the full fact table; keep rows with a prior period.
-- Result: 0 rows - this CMS release publishes ONE reporting period per measure, so LAG() has no prior row.
--         Pattern is the point; re-run after the next quarterly release (Oct 2026) to get real deltas.
-- Original count: 0 rows on 2026-08-25.
SET search_path TO hq;

WITH s AS (
  SELECT v.facility_id, v.period_end, v.score,
         LAG(v.score) OVER (PARTITION BY v.facility_id ORDER BY v.period_end) AS prev_score
  FROM measure_values v JOIN hospitals h USING (facility_id)
  WHERE h.is_texas AND v.measure_id = 'H_HSP_RATING_9_10' AND v.score IS NOT NULL)
SELECT h.facility_name, s.period_end, s.score, s.prev_score, s.score - s.prev_score AS change
FROM s JOIN hospitals h USING (facility_id)
WHERE s.prev_score IS NOT NULL
ORDER BY change DESC;
