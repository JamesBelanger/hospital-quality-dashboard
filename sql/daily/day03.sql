-- DAY 03 (2026-08-28) - card for sql/03_recommend_vs_rating_by_ownership.sql
-- STEP 1: paste this whole file into the Supabase SQL Editor and Run. Note the row count.
-- STEP 2 (the tweak): change   >= 5   to   >= 10
--          why: raise the group-size floor to 10 hospitals - which ownership types vanish?
-- STEP 3: Run again, then fill in today's row in sql/LOG.md.

-- 03_recommend_vs_rating_by_ownership.sql
-- Q: Do patients recommend nonprofits more than for-profits? Avg 'would recommend' and avg star rating by ownership, Texas, groups >= 5 hospitals.
-- Approach: hospitals (Texas) LEFT JOIN latest H_RECMND_DY; GROUP BY ownership with HAVING for the size floor.
-- Result: 9 rows on 2026-08-25.
SET search_path TO hq;

SELECT h.hospital_ownership,
       count(DISTINCT h.facility_id)   AS hospitals,
       round(avg(v.score), 1)          AS avg_recommend_pct,
       round(avg(h.overall_rating), 2) AS avg_star_rating
FROM hospitals h
LEFT JOIN v_tx_latest v ON v.facility_id = h.facility_id AND v.measure_id = 'H_RECMND_DY'
WHERE h.is_texas
GROUP BY 1
HAVING count(DISTINCT h.facility_id) >= 5
ORDER BY avg_recommend_pct DESC NULLS LAST;
