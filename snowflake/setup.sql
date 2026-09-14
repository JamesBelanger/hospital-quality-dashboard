-- setup.sql — Snowflake DDL for the hospital-quality star schema (mirrors schema.sql on PostgreSQL).
-- Section 1: run everything below once, top to bottom, in a Snowsight worksheet.

CREATE WAREHOUSE IF NOT EXISTS HQ_WH
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE;

CREATE DATABASE IF NOT EXISTS HQ;
USE DATABASE HQ;
USE SCHEMA PUBLIC;
USE WAREHOUSE HQ_WH;

CREATE OR REPLACE TABLE hospitals (
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

CREATE OR REPLACE TABLE measures (
    measure_id          VARCHAR,
    domain              VARCHAR,
    measure_name        VARCHAR,
    value_type          VARCHAR,
    n_rows              NUMBER,
    higher_is_better    BOOLEAN
);

CREATE OR REPLACE TABLE measure_values (
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

-- After loading the CSVs (SNOWFLAKE_STEPS.md section 3), sanity-check the row counts:
-- SELECT 'hospitals' t, COUNT(*) FROM hospitals
-- UNION ALL SELECT 'measures', COUNT(*) FROM measures
-- UNION ALL SELECT 'measure_values', COUNT(*) FROM measure_values;
-- Expect roughly: 5,419 / a few hundred / 799,104-ish (rows with scores + nulls).
