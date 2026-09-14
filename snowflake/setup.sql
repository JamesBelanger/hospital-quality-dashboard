-- setup.sql — Snowflake DDL for the hospital-quality star schema (mirrors schema.sql on PostgreSQL).
-- Run ALL of it at once: click into the editor, press Ctrl+A, then Ctrl+Shift+Enter (Run all).
-- Every object below is fully qualified (HQ.PUBLIC.x), so the script works regardless of which
-- database or warehouse the session happens to have selected.

CREATE WAREHOUSE IF NOT EXISTS HQ_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS HQ;

CREATE OR REPLACE TABLE HQ.PUBLIC.hospitals (
    facility_id         VARCHAR PRIMARY KEY,
    facility_name       VARCHAR,
    address             VARCHAR,
    city                VARCHAR,
    state               VARCHAR(2),
    zip_code            VARCHAR,
    county              VARCHAR,
    hospital_type       VARCHAR,
    hospital_ownership  VARCHAR,
    emergency_services  VARCHAR,
    overall_rating      NUMBER,
    is_texas            BOOLEAN,
    is_houston_area     BOOLEAN
);

CREATE OR REPLACE TABLE HQ.PUBLIC.measures (
    measure_id          VARCHAR,
    domain              VARCHAR,
    measure_name        VARCHAR,
    value_type          VARCHAR,
    n_rows              NUMBER,
    higher_is_better    BOOLEAN
);

CREATE OR REPLACE TABLE HQ.PUBLIC.measure_values (
    facility_id         VARCHAR,
    measure_id          VARCHAR,
    measure_name        VARCHAR,
    domain              VARCHAR,
    score               FLOAT,
    denominator         FLOAT,
    lower_estimate      FLOAT,
    upper_estimate      FLOAT,
    compared_to_national VARCHAR,
    value_type          VARCHAR,
    period_start        DATE,
    period_end          DATE
);

-- Sanity check (returns three rows; counts are 0 until the CSVs are loaded in the next step):
SELECT 'hospitals' AS t, COUNT(*) AS n FROM HQ.PUBLIC.hospitals
UNION ALL SELECT 'measures', COUNT(*) FROM HQ.PUBLIC.measures
UNION ALL SELECT 'measure_values', COUNT(*) FROM HQ.PUBLIC.measure_values;
