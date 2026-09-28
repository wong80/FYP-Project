-- Idempotent: safe to run on every start.
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Clean, validated hourly readings. One row per (source, hour).
CREATE TABLE IF NOT EXISTS readings (
    source               text             NOT NULL,
    ts                   timestamptz      NOT NULL,
    "importActiveEnergyT" double precision,
    "currentA"           double precision NOT NULL,
    "currentB"           double precision NOT NULL,
    "currentC"           double precision NOT NULL,
    "voltageA"           double precision NOT NULL,
    "voltageB"           double precision NOT NULL,
    "voltageC"           double precision NOT NULL,
    "activePowerT"       double precision NOT NULL,
    "activePowerA"       double precision NOT NULL,
    "activePowerB"       double precision NOT NULL,
    "activePowerC"       double precision NOT NULL,
    "voltageL12"         double precision,
    "voltageL23"         double precision,
    "voltageL31"         double precision,
    ingested_at          timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (source, ts)
);
SELECT create_hypertable('readings', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

-- Rows that failed a hard check. Kept for review, never deleted (§4.1).
CREATE TABLE IF NOT EXISTS quarantine (
    id          bigserial   PRIMARY KEY,
    source      text        NOT NULL,
    ts          timestamptz,
    reason      text        NOT NULL,
    payload     jsonb       NOT NULL,
    ingest_run  bigint,
    reviewed    boolean     NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS quarantine_source_ts ON quarantine (source, ts);

-- Soft findings on clean rows (energy-rate mismatch, spikes).
CREATE TABLE IF NOT EXISTS data_flags (
    source      text        NOT NULL,
    ts          timestamptz NOT NULL,
    check_name  text        NOT NULL,
    detail      text,
    ingest_run  bigint,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source, ts, check_name)
);

-- One row per ingest job run.
CREATE TABLE IF NOT EXISTS ingest_runs (
    id                bigserial   PRIMARY KEY,
    source            text        NOT NULL,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text        NOT NULL DEFAULT 'running',
    rows_received     integer,
    rows_new          integer,
    rows_clean        integer,
    rows_quarantined  integer,
    gap_hours         integer,
    message           text
);

-- Forecasts are their own table and are never used as training data (§4.1).
-- role: champion (shown), challenger (shadow, logged only), fallback (seasonal naive).
CREATE TABLE IF NOT EXISTS forecasts (
    source         text             NOT NULL,
    target_ts      timestamptz      NOT NULL,
    role           text             NOT NULL,
    model_version  text             NOT NULL,
    predicted_kw   double precision NOT NULL,
    issued_at      timestamptz      NOT NULL DEFAULT now(),
    PRIMARY KEY (source, target_ts, role)
);
SELECT create_hypertable('forecasts', 'target_ts', if_not_exists => TRUE, migrate_data => TRUE);

-- Audit trail of training, gate decisions and promotions (also in MLflow).
CREATE TABLE IF NOT EXISTS model_events (
    id             bigserial   PRIMARY KEY,
    created_at     timestamptz NOT NULL DEFAULT now(),
    event          text        NOT NULL,   -- trained | skipped | promoted | rejected | failed
    model_name     text,
    model_version  text,
    detail         jsonb
);

-- What the dashboard plots: each hour's actual next to the forecast shown for it.
-- 'replay' rows are simulated forecasts over past data (see score.replay).
CREATE OR REPLACE VIEW actual_vs_forecast AS
SELECT f.source,
       f.target_ts                                 AS ts,
       r."activePowerT"                            AS actual_kw,
       f.predicted_kw,
       f.role,
       f.model_version,
       r."activePowerT" - f.predicted_kw           AS error_kw
FROM forecasts f
LEFT JOIN readings r ON r.source = f.source AND r.ts = f.target_ts
WHERE f.role IN ('champion', 'fallback', 'replay');
