-- 05_vs_state_average.sql
-- Q: Each Texas hospital's pneumonia readmission vs the Texas average and vs its county average - benchmarking without a benchmark table.
-- Approach: Two window averages over the same filtered set: AVG() OVER () and AVG() OVER (PARTITION BY county).
-- Result: 258 rows on 2026-08-25.
SET search_path TO hq;

SELECT facility_name, county, score AS readm_30_pn_pct,
       round(avg(score) OVER (), 2)                            AS tx_avg,
       round(score - avg(score) OVER (), 2)                    AS diff_vs_tx,
       round(avg(score) OVER (PARTITION BY county), 2)         AS county_avg,
       round(score - avg(score) OVER (PARTITION BY county), 2) AS diff_vs_county
FROM v_tx_latest
WHERE measure_id = 'READM_30_PN'
ORDER BY diff_vs_tx;
