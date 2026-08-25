-- views.sql — dashboard feeds (Phase 4). Run once against Supabase; etl/extract.py exports them to CSV for Tableau Public.
SET search_path TO hq, public;

-- 1) Scorecard: one row per Texas hospital, six key measures as columns (+ metadata for filters)
CREATE OR REPLACE VIEW v_scorecard AS
SELECT h.facility_id, h.facility_name, h.city, h.county, h.hospital_ownership, h.hospital_type,
       h.overall_rating, h.is_houston_area,
       max(v.score) FILTER (WHERE v.measure_id = 'READM_30_PN')   AS readm_pn_pct,
       max(v.score) FILTER (WHERE v.measure_id = 'READM_30_HF')   AS readm_hf_pct,
       max(v.score) FILTER (WHERE v.measure_id = 'MORT_30_HF')    AS mort_hf_pct,
       max(v.score) FILTER (WHERE v.measure_id = 'MORT_30_PN')    AS mort_pn_pct,
       max(v.score) FILTER (WHERE v.measure_id = 'HAI_1_SIR')     AS hai_clabsi_sir,
       max(v.score) FILTER (WHERE v.measure_id = 'HAI_2_SIR')     AS hai_cauti_sir,
       max(v.score) FILTER (WHERE v.measure_id = 'SEP_1')         AS sepsis_bundle_pct,
       max(v.score) FILTER (WHERE v.measure_id = 'OP_22')         AS ed_left_without_seen_pct,
       max(v.score) FILTER (WHERE v.measure_id = 'H_RECMND_DY')   AS recommend_pct,
       max(v.score) FILTER (WHERE v.measure_id = 'H_HSP_RATING_9_10') AS rated_9_10_pct,
       max(v.score) FILTER (WHERE v.measure_id = 'H_STAR_RATING') AS hcahps_star
FROM hospitals h
LEFT JOIN v_tx_latest v USING (facility_id)
WHERE h.is_texas
GROUP BY h.facility_id, h.facility_name, h.city, h.county, h.hospital_ownership, h.hospital_type, h.overall_rating, h.is_houston_area;

-- 2) Benchmarks: latest value per (hospital, measure) for the key measures, all states,
--    with national + state averages and direction — one long table, Tableau-friendly
CREATE OR REPLACE VIEW v_benchmarks AS
WITH key_measures AS (
  SELECT unnest(ARRAY['READM_30_PN','READM_30_HF','MORT_30_HF','MORT_30_PN','HAI_1_SIR','HAI_2_SIR','SEP_1','OP_22','H_RECMND_DY','H_HSP_RATING_9_10','H_STAR_RATING']) AS measure_id),
latest AS (
  SELECT DISTINCT ON (v.facility_id, v.measure_id) v.facility_id, v.measure_id, v.domain, v.score, v.denominator, v.period_start, v.period_end
  FROM measure_values v JOIN key_measures k USING (measure_id)
  WHERE v.score IS NOT NULL
  ORDER BY v.facility_id, v.measure_id, v.period_end DESC),
dirn AS (SELECT measure_id, bool_or(higher_is_better) AS higher_is_better, min(measure_name) AS measure_name FROM measures GROUP BY 1)
SELECT l.facility_id, h.facility_name, h.state, h.county, h.is_texas, h.is_houston_area, h.hospital_ownership,
       l.measure_id, d.measure_name, l.domain, d.higher_is_better, l.score, l.denominator, l.period_start, l.period_end,
       avg(l.score) OVER (PARTITION BY l.measure_id)          AS national_avg,
       avg(l.score) OVER (PARTITION BY l.measure_id, h.state) AS state_avg,
       percent_rank() OVER (PARTITION BY l.measure_id ORDER BY l.score) AS national_pct_rank
FROM latest l JOIN hospitals h USING (facility_id) JOIN dirn d USING (measure_id);

-- 3) HCAHPS heatmap: Texas hospitals × "top-box" survey answers (answer_percent rows only)
CREATE OR REPLACE VIEW v_hcahps AS
SELECT v.facility_id, v.facility_name, v.county, v.is_houston_area, v.hospital_ownership,
       v.measure_id, v.measure_name, v.score AS top_box_pct, v.denominator AS completed_surveys
FROM v_tx_latest v
WHERE v.domain = 'hcahps' AND v.value_type = 'answer_percent'
  AND v.measure_id IN ('H_RECMND_DY','H_HSP_RATING_9_10','H_COMP_1_A_P','H_COMP_2_A_P','H_COMP_3_A_P','H_COMP_5_A_P','H_COMP_6_Y_P','H_COMP_7_SA','H_CLEAN_HSP_A_P','H_QUIET_HSP_A_P');

-- 4) Texas-vs-national summary per key measure (the one-slide "how does Texas compare")
CREATE OR REPLACE VIEW v_tx_vs_national AS
SELECT measure_id, measure_name, higher_is_better,
       round(avg(score) FILTER (WHERE is_texas)::numeric, 2)                 AS tx_avg,
       round(avg(score)::numeric, 2)                                         AS national_avg,
       count(*) FILTER (WHERE is_texas)                                      AS tx_hospitals,
       count(*) FILTER (WHERE is_texas AND ((higher_is_better AND score > national_avg) OR (NOT higher_is_better AND score < national_avg))) AS tx_beating_national,
       round(100.0 * count(*) FILTER (WHERE is_texas AND ((higher_is_better AND score > national_avg) OR (NOT higher_is_better AND score < national_avg)))
             / NULLIF(count(*) FILTER (WHERE is_texas), 0), 1)               AS tx_share_beating_pct
FROM v_benchmarks
GROUP BY measure_id, measure_name, higher_is_better
ORDER BY tx_share_beating_pct DESC;
