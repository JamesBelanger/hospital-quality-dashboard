-- 08_quality_composite.sql
-- Q: A 3-domain quality composite for Texas hospitals: z(readmission, sign-flipped) + z(recommend) + z(sepsis care), averaged. Top 10 and bottom 10.
-- Approach: One CTE per domain computing a z-score with window AVG/STDDEV over Texas; final CTE joins the three; UNION of top/bottom slices.
-- Result: 20 rows on 2026-08-25.
SET search_path TO hq;

WITH readm AS (
  SELECT facility_id, -(score - avg(score) OVER ()) / NULLIF(stddev(score) OVER (), 0) AS z_readm
  FROM v_tx_latest WHERE measure_id = 'READM_30_PN'),
rec AS (
  SELECT facility_id, (score - avg(score) OVER ()) / NULLIF(stddev(score) OVER (), 0) AS z_recommend
  FROM v_tx_latest WHERE measure_id = 'H_RECMND_DY'),
sep AS (
  SELECT facility_id, (score - avg(score) OVER ()) / NULLIF(stddev(score) OVER (), 0) AS z_sepsis
  FROM v_tx_latest WHERE measure_id = 'SEP_1'),
comp AS (
  SELECT h.facility_name, h.county,
         round(z_readm::numeric, 2) AS z_readm, round(z_recommend::numeric, 2) AS z_recommend, round(z_sepsis::numeric, 2) AS z_sepsis,
         round(((z_readm + z_recommend + z_sepsis) / 3)::numeric, 2) AS composite
  FROM hospitals h JOIN readm USING (facility_id) JOIN rec USING (facility_id) JOIN sep USING (facility_id))
(SELECT 'top' AS bucket, * FROM comp ORDER BY composite DESC LIMIT 10)
UNION ALL
(SELECT 'bottom' AS bucket, * FROM comp ORDER BY composite ASC LIMIT 10);
