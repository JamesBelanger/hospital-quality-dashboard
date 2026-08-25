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
