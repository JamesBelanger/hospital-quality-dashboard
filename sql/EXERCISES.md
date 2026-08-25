# SQL exercises — Houston Hospital Quality Explorer

Twelve questions, each a real analyst task on this data. **James writes every query himself** in the Supabase SQL editor; Claude reviews (correctness → style → a cleaner variant) and only then it gets saved as `sql/NN_name.sql` with a header comment (question · approach · rows returned) and a dated line in `sql/LOG.md`. Do 1–2 per sitting; the point is the *daily* log, not speed.

Tables: `hq.hospitals` (dim), `hq.measures` (dim), `hq.measure_values` (fact, long), view `hq.v_tx_latest` (latest period, Texas, non-null). Run `SET search_path TO hq;` first.

**Measure IDs you'll use** (they're real CMS IDs — worth memorizing, they appear in every hospital-analytics job):
- Readmissions (`unplanned_visits`, lower is better): `Hybrid_HWR` (hospital-wide), `READM_30_HF`, `READM_30_AMI`, `READM_30_PN`, `READM_30_HIP_KNEE`
- Mortality (`complications_deaths`, lower): `MORT_30_HF`, `MORT_30_AMI`, `MORT_30_PN`, `MORT_30_STK`; safety composite `PSI_90`
- Infections (`hai`, lower; SIR = standardized infection ratio, 1.0 = national expectation): `HAI_1_SIR` (central-line), `HAI_2_SIR` (catheter UTI)
- Timely & effective (`timely_effective`): `OP_22` (% left ED without being seen, lower), `SEP_1` (sepsis bundle %, higher), `IMM_3` (staff flu vaccination %, higher), `EDV` (ED volume category — text-ish)
- Patient experience (`hcahps`, higher, value_type = answer_percent unless noted): `H_RECMND_DY` (would definitely recommend), `H_HSP_RATING_9_10` (rated 9–10), `H_COMP_1_A_P` (nurses always communicated well), `H_CLEAN_HSP_A_P`, `H_QUIET_HSP_A_P`, `H_STAR_RATING` (value_type = star_rating)

---

## Tier 1 — joins (warm-up; 3 exercises)

**01_houston_readmit_scorecard** — For every Houston-area hospital, show name, county, ownership, overall star rating, and its hospital-wide readmission score (`Hybrid_HWR`, latest period). Include hospitals with no score (LEFT JOIN). Sort by score ascending.
*Analyst task: the first table every quality-team meeting starts with.*

**02_sparse_measures_tx** — Which measures are missing (NULL score) for more than 50% of Texas hospitals? Return measure_id, domain, measure_name, hospitals_with_score, hospitals_total, pct_missing. Sort by pct_missing desc.
*Analyst task: data-completeness audit before anyone trusts a dashboard.*

**03_recommend_vs_rating_by_ownership** — For Texas hospitals, average `H_RECMND_DY` and average `overall_rating` grouped by `hospital_ownership`; include hospital count per group; only groups with ≥5 hospitals. Sort by avg recommend desc.
*Analyst task: "do patients recommend nonprofits more than for-profits?" — a real exec question.*

## Tier 2 — window functions (4 exercises)

**04_rank_within_county** — Rank Houston-area hospitals by `READM_30_HF` (heart-failure readmission) *within each county* using `RANK() OVER (PARTITION BY county ORDER BY score)`. Show county, rank, hospital, score. Lower is better, so rank 1 = best.

**05_vs_state_average** — For every Texas hospital with a `Hybrid_HWR` score, show its score, the Texas average (`AVG(score) OVER ()`), and the difference. Then add the *county* average as a second window column. Sort by difference (most below average first).
*This is "benchmarking without a benchmark table" — the design decision from the README.*

**06_national_percentile** — Using ALL states (query `measure_values` + `hospitals`, not the Texas view), compute each hospital's national percentile on `MORT_30_HF` with `PERCENT_RANK() OVER (ORDER BY score)`. Return only Houston-area hospitals with their percentile. Interpret: is a low percentile good or bad here?

**07_period_over_period** — For `H_HSP_RATING_9_10`, some hospitals have more than one reporting period in the fact table. Using `LAG(score) OVER (PARTITION BY facility_id ORDER BY period_end)`, compute each Texas hospital's change from the prior period. Return the 10 biggest improvements and the 10 biggest declines. (If only one period exists in this release, say so in the header comment and demonstrate the query on `period_end` anyway — the pattern is the skill.)

## Tier 3 — CTEs (3 exercises)

**08_quality_composite** — Build a composite score for Texas hospitals from three domains: z-score each of `Hybrid_HWR` (readmission, flip sign so higher = better), `H_RECMND_DY` (recommend), and `SEP_1` (sepsis care) across Texas, then average the three z-scores per hospital. Use one CTE per domain + a final CTE that joins them. Return the top 10 and bottom 10 with all three z's shown.
*Analyst task: the "overall quality index" leadership always asks for — and the one you should be able to explain the arbitrariness of.*

**09_mismatch_finder** — Find Texas hospitals that are *better than the state average* on readmission (`Hybrid_HWR` below TX mean) but *worse than average* on patient experience (`H_RECMND_DY` below TX mean). Use CTEs for the two averages. Return hospital, county, both scores, both averages.
*Analyst task: the interesting quadrant — clinically good, experientially weak. Great dashboard annotation material.*

**10_county_rollup** — County-level roll-up for Texas: hospital count, count with a `Hybrid_HWR` score, mean readmission score, and a *denominator-weighted* mean readmission (`SUM(score*denominator)/SUM(denominator)`). CTE for per-hospital latest values, then aggregate. Sort by weighted mean. Why do the two means differ?

## Tier 4 — aggregation & pivot (2 exercises)

**11_scorecard_pivot** — One row per Houston-area hospital with columns: `readm_hwr`, `mort_hf`, `hai_clabsi_sir`, `sepsis_pct`, `recommend_pct`, `star_rating` — pulled from the long table with `MAX(score) FILTER (WHERE measure_id = '...')` (or CASE WHEN). Sort by recommend_pct desc. This is the dashboard extract shape.

**12_beat_national_share** — For each of the six measures in exercise 11, what share of Texas hospitals beat the *national* average (computed from all states)? Return measure_id, tx_hospitals, tx_beating_national, share. Handle direction correctly (`higher_is_better` from `measures`).
*Analyst task: the "how does Texas compare" one-slide summary.*

---

## Stretch (for the "Sr" tiers later, not required for DoD)
- **S1** Materialize the exercise-11 scorecard as `hq.mv_scorecard` (`CREATE MATERIALIZED VIEW`) and add an index; time a query before/after.
- **S2** `EXPLAIN (ANALYZE)` exercise 06 on the full fact table; identify the slow step; add the index that fixes it.
- **S3** Refine `measures.higher_is_better` for the HCAHPS rows left NULL with an `UPDATE ... WHERE measure_name ILIKE ...` — document your rule.

## Header template for each saved file
```sql
-- 04_rank_within_county.sql
-- Q: Rank Houston-area hospitals by heart-failure readmission within each county (rank 1 = best).
-- Approach: v_tx_latest filtered to READM_30_HF + is_houston_area; RANK() OVER (PARTITION BY county ORDER BY score).
-- Result: 71 rows (2026-08-27). Notes: 2 hospitals had no score → excluded by the view.
```
