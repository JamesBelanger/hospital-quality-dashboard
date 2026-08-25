-- DAY 04 (2026-08-29) - card for sql/04_rank_within_county.sql
-- STEP 1: paste this whole file into the Supabase SQL Editor and Run. Note the row count.
-- STEP 2 (the tweak): change   'READM_30_HF'   to   'MORT_30_HF'
--          why: rank by heart-failure MORTALITY instead. Same direction (lower = better), so rank 1 is still best.
-- STEP 3: Run again, then fill in today's row in sql/LOG.md.

-- 04_rank_within_county.sql
-- Q: Rank Houston-area hospitals by heart-failure readmission within each county (rank 1 = best).
-- Approach: v_tx_latest filtered to READM_30_HF + is_houston_area; RANK() OVER (PARTITION BY county ORDER BY score).
-- Result: 34 rows on 2026-08-25.
SET search_path TO hq;

SELECT county,
       RANK() OVER (PARTITION BY county ORDER BY score) AS rank_in_county,
       facility_name,
       score AS readm_30_hf_pct
FROM v_tx_latest
WHERE measure_id = 'READM_30_HF' AND is_houston_area
ORDER BY county, rank_in_county;
