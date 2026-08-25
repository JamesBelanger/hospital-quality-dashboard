-- DAY 01 (2026-08-26) - card for sql/01_houston_readmit_scorecard.sql
-- STEP 1: paste this whole file into the Supabase SQL Editor and Run. Note the row count.
-- STEP 2 (the tweak): change   'READM_30_PN'   to   'READM_30_HF'
--          why: swap the measure: pneumonia -> heart-failure readmission. Watch which hospitals drop out (fewer HF-scored hospitals).
-- STEP 3: Run again, then fill in today's row in sql/LOG.md.

-- 01_houston_readmit_scorecard.sql
-- Q: Every Houston-area hospital with name, county, ownership, star rating and its pneumonia
--    30-day readmission score (READM_30_PN, latest period). Hospitals with no score included.
-- Result: 73 rows (34 scored) on 2026-08-25.
-- Approach: start from hospitals (so unscored ones survive) and LEFT JOIN the latest-period view
--    filtered to the one measure. NULLS LAST so the scored hospitals lead.
SET search_path TO hq;

SELECT h.facility_name,
       h.county,
       h.hospital_ownership,
       h.overall_rating           AS star_rating,
       v.score                    AS readm_30_pn_pct,
       v.denominator              AS eligible_discharges,
       v.period_start, v.period_end
FROM hospitals h
LEFT JOIN v_tx_latest v
       ON v.facility_id = h.facility_id
      AND v.measure_id = 'READM_30_PN'
WHERE h.is_houston_area
ORDER BY v.score ASC NULLS LAST, h.facility_name;
