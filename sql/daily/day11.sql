-- DAY 11 (2026-09-05) - card for sql/11_scorecard_pivot.sql
-- STEP 1: paste this whole file into the Supabase SQL Editor and Run. Note the row count.
-- STEP 2 (the tweak): change   ORDER BY recommend_pct DESC NULLS LAST   to   ORDER BY readm_pn ASC NULLS LAST
--          why: sort the scorecard by readmission (best first) instead of recommend %.
-- STEP 3: Run again, then fill in today's row in sql/LOG.md.

-- 11_scorecard_pivot.sql
-- Q: One row per Houston-area hospital with six key measures as columns - the dashboard extract shape.
-- Approach: Conditional aggregation: MAX(score) FILTER (WHERE measure_id = ...) over the long table, grouped by hospital.
-- Result: 53 rows on 2026-08-25.
SET search_path TO hq;

SELECT facility_name, county,
       max(score) FILTER (WHERE measure_id = 'READM_30_PN')   AS readm_pn,
       max(score) FILTER (WHERE measure_id = 'MORT_30_HF')    AS mort_hf,
       max(score) FILTER (WHERE measure_id = 'HAI_1_SIR')     AS hai_clabsi_sir,
       max(score) FILTER (WHERE measure_id = 'SEP_1')         AS sepsis_pct,
       max(score) FILTER (WHERE measure_id = 'H_RECMND_DY')   AS recommend_pct,
       max(score) FILTER (WHERE measure_id = 'H_STAR_RATING') AS star_rating
FROM v_tx_latest
WHERE is_houston_area
GROUP BY facility_name, county
ORDER BY recommend_pct DESC NULLS LAST;
