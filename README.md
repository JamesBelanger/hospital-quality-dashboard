# Houston Hospital Quality Explorer

A public BI portfolio project: CMS Care Compare hospital-quality data (30-day readmissions, HCAHPS patient experience, timely & effective care, complications, infections) for Texas hospitals, loaded into Postgres (Supabase), analyzed with SQL, and published as a Tableau Public dashboard + a self-contained web version.

**Status:** scaffolded 2026-08-25 · driven by the `/goal bi-dashboard` spec.

## Layout
- `etl/` — `download.py` (CMS provider-data pull), `clean.py` (tidy long table), `load.py` (→ Postgres)
- `schema.sql` — star-ish schema: `hospitals`, `measures`, `measure_values`, `benchmarks`
- `sql/` — `EXERCISES.md` (12 analyst-task questions), `NN_name.sql` (solved by James), `views.sql`, `LOG.md` (daily SQL log)
- `dashboard/` — `SPEC.md`, `extracts/` (CSV feeds for Tableau Public), `web/index.html` (Plotly version)
- `data/` — manifest of source datasets (raw CSVs are gitignored)


## Schema (why it looks like this)
- **`hq.hospitals`** (5,419 rows) — one row per CMS facility; `is_texas` / `is_houston_area` flags precomputed so every Texas query is a boolean filter, not a string match on county names.
- **`hq.measures`** (168 rows) — one row per (measure_id, domain). `higher_is_better` is a *heuristic* column (readmissions/mortality/infections/wait-times = lower is better; process-of-care percentages and HCAHPS "top-box" answers = higher is better; ambiguous HCAHPS answer rows left NULL). Refining it is exercise material, not ETL magic.
- **`hq.measure_values`** (~800k rows) — one long/tidy fact row per (facility, measure, period, value). Six CMS files with six different column layouts all reduce to this one shape, which means one schema, one set of indexes, and one SQL vocabulary for everything.
- **Benchmarks are computed, not loaded.** CMS publishes state/national benchmark files, but deriving them with `AVG(...) OVER (PARTITION BY state)` from hospital-level rows is the point of the SQL practice — and it keeps the load step to three tables.
- **`hq.v_tx_latest`** — the dashboard's base view: latest period per (hospital, measure), Texas only, non-null scores.

## Findings
_(filled in at Phase 5)_

## Method & limitations
_(filled in at Phase 5)_

## Interactive explorer (`dashboard/explorer/`)

A static, no-backend web app (vanilla ES modules + D3 v7) built from the same tables. Live at
https://jamesbelanger.com/projects/hospital-quality/explore/.

| Tab | What it does | SQL behind it |
|---|---|---|
| Story | Scrollytelling intro: 3,049 US hospitals → Texas → Houston → one hospital → the outcomes-vs-experience mismatch | `06`, `09` |
| Report card | Search any of 5,419 hospitals; every key measure placed on the peer-group distribution with a direction-aware "beats X% of peers" badge; shareable URL; CSV | `06_national_percentile` |
| Compare | Brush a measure's distribution; the scorecard table and HCAHPS heatmap follow; hover a row to find its dot | `05`, `11`, `v_hcahps` |
| Measures | All 161 measures: national vs peer histogram, best/worst ten, missingness | `02_sparse_measures_tx` |
| Map | State choropleth of medians → zoom into a state for hospital dots colored by peer percentile | `10_county_rollup` |
| Rankings | Five-slider weighted composite that re-ranks live (illustrative, not CMS stars) + mismatch quadrant with brush | `08`, `09` |
| SQL | DuckDB-WASM console over the Parquet export of `hospitals` / `measures` / `measure_values` + the five views; the twelve exercises as presets | all |

Build the data bundle: `python etl/export_web.py --assets <dir with 2023_Gaz_zcta_national.txt, states-10m.json, counties-10m.json>`
(ZIP-centroid geocoding from the Census ZCTA gazetteer; maps from us-atlas). Serve locally with
`python -m http.server` from `dashboard/explorer/`. Peer groups (scope × ownership × type × ED) are shared
across tabs via the bar under the header; state lives in the URL hash so any view is linkable.
