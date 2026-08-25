-- schema.sql — Houston Hospital Quality Explorer (Postgres / Supabase)
-- Star-ish schema: two dimensions (hospitals, measures) + one long fact table (measure_values).
-- Benchmarks are intentionally NOT a loaded table: state/national reference values are computed
-- in SQL from hospital-level rows (see sql/EXERCISES.md — window functions).

CREATE SCHEMA IF NOT EXISTS hq;
SET search_path TO hq, public;

DROP TABLE IF EXISTS measure_values;
DROP TABLE IF EXISTS measures;
DROP TABLE IF EXISTS hospitals;

CREATE TABLE hospitals (
    facility_id         text PRIMARY KEY,
    facility_name       text NOT NULL,
    address             text,
    city                text,
    state               char(2),
    zip_code            text,
    county              text,
    hospital_type       text,
    hospital_ownership  text,
    emergency_services  text,
    overall_rating      smallint CHECK (overall_rating BETWEEN 1 AND 5),
    is_texas            boolean NOT NULL DEFAULT false,
    is_houston_area     boolean NOT NULL DEFAULT false
);

CREATE TABLE measures (
    measure_id          text NOT NULL,
    domain              text NOT NULL CHECK (domain IN ('unplanned_visits','timely_effective','complications_deaths','hai','hcahps')),
    measure_name        text,
    value_type          text,           -- score | answer_percent | linear_mean | star_rating
    n_rows              integer,
    higher_is_better    boolean,        -- NULL = undecided (HCAHPS non-"top box" answer rows); refine in SQL
    PRIMARY KEY (measure_id, domain)
);

CREATE TABLE measure_values (
    id                  bigserial PRIMARY KEY,
    facility_id         text NOT NULL REFERENCES hospitals(facility_id),
    measure_id          text NOT NULL,
    domain              text NOT NULL,
    measure_name        text,
    score               numeric,
    denominator         numeric,
    lower_estimate      numeric,
    upper_estimate      numeric,
    compared_to_national text,
    value_type          text,
    period_start        date,
    period_end          date,
    FOREIGN KEY (measure_id, domain) REFERENCES measures(measure_id, domain)
);

CREATE INDEX ON measure_values (measure_id);
CREATE INDEX ON measure_values (facility_id);
CREATE INDEX ON measure_values (domain, measure_id) WHERE score IS NOT NULL;
CREATE INDEX ON hospitals (state) WHERE is_texas;

-- Convenience view: one row per (hospital, measure) with the latest period, Texas only — the dashboard's base
CREATE OR REPLACE VIEW v_tx_latest AS
SELECT DISTINCT ON (mv.facility_id, mv.measure_id, mv.domain)
       h.facility_id, h.facility_name, h.city, h.county, h.hospital_ownership, h.overall_rating, h.is_houston_area,
       mv.domain, mv.measure_id, mv.measure_name, mv.value_type, mv.score, mv.denominator,
       mv.lower_estimate, mv.upper_estimate, mv.compared_to_national, mv.period_start, mv.period_end
FROM measure_values mv
JOIN hospitals h USING (facility_id)
WHERE h.is_texas AND mv.score IS NOT NULL
ORDER BY mv.facility_id, mv.measure_id, mv.domain, mv.period_end DESC NULLS LAST;
