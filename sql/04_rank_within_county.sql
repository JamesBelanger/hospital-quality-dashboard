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
