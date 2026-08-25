-- 02_sparse_measures_tx.sql
-- Q: Which measures are missing (NULL score) for >50% of Texas hospitals?
-- Approach: Count distinct Texas hospitals with a non-null score per measure vs total Texas hospitals; LEFT JOIN so zero-coverage measures (Hybrid_HWR) appear.
-- Result: 90 rows on 2026-08-25.
SET search_path TO hq;

WITH tx AS (SELECT facility_id FROM hospitals WHERE is_texas),
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
ORDER BY pct_missing DESC, measure_id;
