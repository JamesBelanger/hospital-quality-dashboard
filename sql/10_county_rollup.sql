-- 10_county_rollup.sql
-- Q: County roll-up for Texas: hospitals, hospitals with a readmission score, plain mean vs denominator-weighted mean (counties with >= 3 scored hospitals).
-- Approach: Per-hospital CTE (LEFT JOIN so unscored hospitals count), then GROUP BY county; weighted mean = SUM(score*denominator)/SUM(denominator).
-- Result: 20 rows on 2026-08-25.
SET search_path TO hq;

WITH per AS (
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
ORDER BY weighted_mean_readm NULLS LAST;
