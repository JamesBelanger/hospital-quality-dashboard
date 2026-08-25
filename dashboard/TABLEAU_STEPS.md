# Tableau Public build — click-by-click (James, ~60–90 min)

Files: `dashboard/extracts/scorecard.csv`, `benchmarks.csv`, `hcahps.csv`, `tx_vs_national.csv`. Open **Tableau Desktop Public Edition**, sign in.

## 0. Connect (2 min — simplest path)
1. Start page → **Connect → To a File → Microsoft Excel** → pick `dashboard/extracts/dashboard_source.xlsx` (all four feeds are sheets in this one workbook).
2. Drag the **scorecard** sheet onto the canvas. For each of the other sheets, use **Data → New Data Source → Microsoft Excel** (same file) so each sheet is its own data source — no joins needed. (CSV fallback: the four `.csv` files sit next to the workbook.)
3. Check types: in each source, `facility_id` should be a **String** (Abc), scores **Number (decimal)**, `is_houston_area` **Boolean**. Click the data-type icon above a column to change it.

## 1. Sheet "Scorecard" — highlight table (15 min)
Source: scorecard. Drag **facility_name** to Rows. Drag **Measure Names** to Columns, **Measure Values** to Text (Marks). In the Measure Values shelf keep only: readm_pn_pct, mort_hf_pct, hai_clabsi_sir, sepsis_bundle_pct, recommend_pct, hcahps_star (drag the rest off). Marks type → **Square**; drag **Measure Values** onto **Color** → click Color → *Use separate legends*. Set each legend: readmission / mortality / CLABSI → Orange-Blue *reversed* (low = blue); the other three → Blue. Filter: drag **is_houston_area** to Filters → True. Sort: click recommend_pct header → sort descending. Rename columns (right-click header → Edit alias): "Pneumonia readm % ▼", "HF mortality % ▼", "CLABSI SIR ▼", "Sepsis bundle % ▲", "Recommend % ▲", "HCAHPS stars ▲".

## 2. Sheet "Readmission vs benchmarks" — dot plot (15 min)
Source: benchmarks. Filters: **measure_id** = READM_30_PN. Columns: **score** (continuous). Rows: **is_houston_area** (so Houston hospitals get their own strip). Marks: Circle; Color: is_houston_area (blue for TRUE, gray for FALSE); Size: small; Detail: facility_name; Tooltip: facility_name, county, score, national_pct_rank. Reference lines: right-click the x-axis → **Add Reference Line** → Value: **national_avg** (Average) → label "National avg"; repeat with **state_avg** → "Texas avg" (dark teal). Annotate the best Houston dot: right-click it → Annotate → Mark.

## 3. Sheet "Patient experience" — heatmap (10 min)
Source: hcahps. Filters: is_houston_area = True. Rows: **facility_name**. Columns: **measure_name** (or measure_id, then alias each to the short question label). Marks: Square; Color: **top_box_pct** (Blues, range 40–95); Label: top_box_pct (0 decimals). Sort rows by H_RECMND_DY descending (sort icon on the Rows pill → by field top_box_pct, filtered to H_RECMND_DY).

## 4. Sheet "Texas vs national" — bar (10 min)
Source: tx_vs_national. Rows: **measure_name** (alias to short labels). Columns: **tx_share_beating_pct**. Marks: Bar; Color: a calculated field `[tx_share_beating_pct] >= 50` (teal/orange); Label: tx_share_beating_pct. Add a constant reference line at 50 (dotted). Sort descending.

## 5. Dashboard (15 min)
New Dashboard → Size: **Custom 1200 × 900**. Layout: left column (220 px) = title text object + a **filter bar** (from sheet 1, show filter for county & hospital_ownership; set them to *Apply to Worksheets → All using related data sources* — or simply per-sheet); right: sheet 1 on top (height ~40%), then sheets 2 and 3 side by side, sheet 4 bottom. Add 4 **Text objects** with the headline findings (copy from `SPEC.md`). Add a small footer text with the method + limitations sentence.

## 6. Publish (5 min)
**File → Save to Tableau Public As…** → title "Houston Hospital Quality Explorer" → Save. Tableau opens the published page. Toggle **"Show sheets as tabs"** off, keep **"Allow access"** on so it's embeddable. Click **Share** → copy the **Embed Code** and the **Link**. Paste both into `dashboard/PUBLISHED.md` (create it) and tell Claude — that unlocks the site page.

Tips: Ctrl+Z is generous; "Show Me" (top right) is fine for the first pass of any sheet; if a CSV won't load, open it once in Excel and re-save as CSV UTF-8.
