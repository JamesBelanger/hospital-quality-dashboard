# Dashboard spec — Houston Hospital Quality Explorer

**Audience:** a hospital quality/BI team or a county public-health analyst. **Goal of the artifact:** show, in one screen, how Houston-area hospitals compare on the four things every quality meeting starts with — readmissions, mortality, infections, patient experience — against Texas and national benchmarks, with the data caveats stated on the page.

**Data feeds (dashboard/extracts/):** `scorecard.csv` (one row per Texas hospital, measures as columns), `benchmarks.csv` (long: TX hospital × key measure, with national/state averages + national percentile), `benchmarks_all.csv` (national distribution per measure), `hcahps.csv` (TX hospital × survey question), `tx_vs_national.csv` (one row per measure summary).

**Tool:** Tableau Public (published, embeddable) + a self-contained Plotly HTML twin for the website.

## Views (one dashboard, 4 panels + a filter bar)

**Filters (global):** County (Harris / Fort Bend / Montgomery / Brazoria / Galveston / all Texas) · Ownership · Hospital (multi-select) · a "Houston area only" toggle (default ON).

1. **Scorecard (table + bars)** — from `scorecard.csv`. Rows = hospitals; columns = readm_pn_pct, mort_hf_pct, hai_clabsi_sir, sepsis_bundle_pct, recommend_pct, hcahps_star. Bars inside cells; color = better/worse than Texas average (direction-aware — lower is better for the first three). Sort default: recommend_pct desc. Tooltip: eligible-discharge denominator + period.
2. **Readmission vs benchmark (dot plot)** — from `benchmarks.csv` filtered to READM_30_PN. Each hospital a dot on the x-axis (score); vertical reference lines for Texas average and national average; Houston-area dots highlighted; hover = hospital, score, national percentile. Annotation callout: the best Houston hospital and the mismatch quadrant from exercise 09.
3. **Patient-experience heatmap** — from `hcahps.csv`. Rows = Houston-area hospitals; columns = the 10 top-box questions (recommend, 9–10 rating, nurse/doctor communication, responsiveness, medicines, discharge info, care transition, cleanliness, quiet); color = top-box %; sorted by recommend_pct.
4. **Texas vs national (bar)** — from `tx_vs_national.csv`. One bar per key measure = share of Texas hospitals beating the national average (53–73% on 10 of 11 measures); tooltip shows TX avg vs national avg and n.

**Headline findings to annotate (from the exercises):**
- Houston Methodist Hospital sits at the **0.4th percentile nationally on heart-failure mortality (6.0%)** — the best Houston-area hospital on that measure (ex. 06).
- **Texas hospitals beat the national average on 10 of 11 key measures** — 53–73% of Texas hospitals are on the good side of the national mean (strongest: catheter-UTI infections 73%, ED walk-outs 66%, HF mortality 64%); the one exception is the HCAHPS summary star rating (40%) (ex. 12 / v_tx_vs_national).
- **Clinically-good / experientially-weak quadrant:** 66 Texas hospitals beat the state on pneumonia readmission but fall below it on "would recommend" (ex. 09) — the dashboard's most discussable cell.
- **Coverage caveat:** 90 of 168 measures are missing for >50% of Texas hospitals, and the hospital-wide readmission measure (Hybrid_HWR) is unscored for every hospital this release (ex. 02) — state it on the page; it's what a real analyst would flag first.

**Color rules:** sequential blue for "higher is better," sequential orange for "lower is better," neutral gray for missing; benchmark lines in black (national) and dark teal (Texas). Direction icons (▲/▼) next to column headers so no one reads a readmission bar as "more is good."

**Build order in Tableau Public (James, ~60–90 min with the step-by-step):** connect the four CSVs → build panel 1 as a highlight table → panel 2 as a dot plot with reference lines → panel 3 heatmap → panel 4 bar → assemble on one dashboard (1200×900) with the filter bar on the left → add the four annotations → publish → copy embed code + URL into `dashboard/PUBLISHED.md`.
