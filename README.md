# Houston Hospital Quality Explorer

A public BI portfolio project: CMS Care Compare hospital-quality data (30-day readmissions, HCAHPS patient experience, timely & effective care, complications, infections) for Texas hospitals, loaded into Postgres (Supabase), analyzed with SQL, and published as a Tableau Public dashboard + a self-contained web version.

**Status:** scaffolded 2026-08-25 · driven by the `/goal bi-dashboard` spec.

## Layout
- `etl/` — `download.py` (CMS provider-data pull), `clean.py` (tidy long table), `load.py` (→ Postgres)
- `schema.sql` — star-ish schema: `hospitals`, `measures`, `measure_values`, `benchmarks`
- `sql/` — `EXERCISES.md` (12 analyst-task questions), `NN_name.sql` (solved by James), `views.sql`, `LOG.md` (daily SQL log)
- `dashboard/` — `SPEC.md`, `extracts/` (CSV feeds for Tableau Public), `web/index.html` (Plotly version)
- `data/` — manifest of source datasets (raw CSVs are gitignored)

## Findings
_(filled in at Phase 5)_

## Method & limitations
_(filled in at Phase 5)_
