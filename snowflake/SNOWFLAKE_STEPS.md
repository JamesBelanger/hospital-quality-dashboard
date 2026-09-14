# Snowflake hands-on: load the hospital star schema (James-only steps, ~1.5 hrs)

Goal: honest resume line "Snowflake (hands-on): loaded a 799k-row star schema, analytical queries."
Everything you need is in this folder: `setup.sql` (DDL) and `queries.sql` (four analyses).

## 1. Create the free trial (~10 min)
1. Go to **signup.snowflake.com** → Start for free.
2. Name/email: use jamesluibelanger@gmail.com. Company: "Personal project" is fine.
3. Choose **Standard** edition, cloud **AWS**, region **US East (N. Virginia)**. No credit card needed;
   you get 30 days / $400 of credits (this project will use well under $5).
4. Activate via the email link, set username + password (SAVE THESE), and you land in **Snowsight**
   (the web UI).

## 2. Create the database and warehouse (~5 min)
1. Left sidebar → **Projects → Worksheets** → "+ Worksheet".
2. Paste the CREATE statements from `setup.sql` **section 1** and click the ▶ Run All button.
   This makes warehouse `HQ_WH` (X-Small, auto-suspend 60s), database `HQ`, schema `PUBLIC`,
   and the three empty tables.

## 3. Load the three CSVs (~20 min)
Files are in `C:\Users\james\projects\hospital-quality-dashboard\data\processed\`
(hospitals.csv 0.8 MB, measures.csv 22 KB, measure_values.csv **137 MB** — under Snowsight's 250 MB limit).

For EACH of the three tables:
1. Sidebar → **Data → Databases → HQ → PUBLIC → Tables** → click the table (e.g. HOSPITALS)
   → **Load Data** button (top right).
2. Warehouse: HQ_WH. Browse → pick the matching CSV.
3. File format: **Delimited (CSV)**, header = **Skip first line**, delimiter comma,
   "Optionally enclosed by" = double quote. Leave the rest default.
4. On the column-match screen it should map by position/name; click **Load**.
   measure_values.csv takes a few minutes to upload — leave the tab open.
5. If a load errors on a column: screenshot the message and tell Claude; the likely fix is
   "Date format: AUTO" or allowing empty values as NULL ("Replace empty with NULL").

## 4. Run the analyses (~15 min)
Open a new worksheet, paste ALL of `queries.sql`, run statement by statement (Ctrl+Enter runs the
statement under the cursor). The four queries mirror the PostgreSQL exercises but use Snowflake
idioms — `QUALIFY ROW_NUMBER()` instead of `DISTINCT ON`, `COUNT_IF` instead of `FILTER (WHERE)`.
Expected shapes: Q1 ≈ 32 rows (Houston HF-mortality percentiles), Q2 = 11 rows (TX vs national),
Q3 ≈ 20 rows, Q4 = 90 rows. If anything errors, copy the message to Claude.

## 5. Wrap up (~5 min)
1. Screenshot one result grid (Q1 is the photogenic one).
2. Tell Claude "Snowflake done" → the resume skills line gains
   "Snowflake (hands-on: 799k-row star schema + analytical queries)" and, optionally, a short
   note goes on the site.
3. Nothing to cancel — the trial expires by itself; HQ_WH auto-suspends after 60 seconds idle,
   so credits barely burn.

## Talking points once done (for Redpoint/interviews)
- "Same star schema runs on PostgreSQL and Snowflake; the only real porting work was DISTINCT ON →
  QUALIFY and FILTER → COUNT_IF" — shows dialect fluency, not tool-brand loyalty.
- Snowsight's Load Data wizard is the manual version of what Fivetran/Matillion automate — you
  understand the pipeline those tools productize.
