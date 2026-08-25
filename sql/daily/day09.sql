-- DAY 09 (2026-09-03) - card for sql/09_mismatch_finder.sql
-- STEP 1: paste this whole file into the Supabase SQL Editor and Run. Note the row count.
-- STEP 2 (the tweak): change   r.readm < a.avg_readm AND p.recommend < a.avg_recommend   to   r.readm > a.avg_readm AND p.recommend > a.avg_recommend
--          why: flip the quadrant: WORSE readmission but BETTER experience. Which hospitals live there?
-- STEP 3: Run again, then fill in today's row in sql/LOG.md.

-- 09_mismatch_finder.sql
-- Q: Texas hospitals better than the state average on readmission but worse on patient experience - the clinically-good / experientially-weak quadrant.
-- Approach: Two CTEs for the two measures, a CTE of their Texas averages, CROSS JOIN the averages into the comparison.
-- Result: 66 rows on 2026-08-25.
SET search_path TO hq;

WITH r AS (SELECT facility_id, score AS readm FROM v_tx_latest WHERE measure_id = 'READM_30_PN'),
     p AS (SELECT facility_id, score AS recommend FROM v_tx_latest WHERE measure_id = 'H_RECMND_DY'),
     a AS (SELECT (SELECT avg(readm) FROM r) AS avg_readm, (SELECT avg(recommend) FROM p) AS avg_recommend)
SELECT h.facility_name, h.county,
       r.readm, round(a.avg_readm, 2) AS tx_avg_readm,
       p.recommend, round(a.avg_recommend, 1) AS tx_avg_recommend
FROM hospitals h JOIN r USING (facility_id) JOIN p USING (facility_id) CROSS JOIN a
WHERE r.readm < a.avg_readm AND p.recommend < a.avg_recommend
ORDER BY r.readm;
