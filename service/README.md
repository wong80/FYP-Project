# Chiller forecast service — runbook

Hourly one-hour-ahead forecasts of chiller power, shown on a Grafana dashboard,
with a weekly retrain that only goes live if it passes the guardrails.
Design and reasoning: [`docs/online-deployment/DESIGN.md`](../docs/online-deployment/DESIGN.md).

## What runs

| Container | Does | When |
|---|---|---|
| `db` | TimescaleDB: readings, quarantine, forecasts, audit tables | always |
| `mlflow` | Model registry + training history (<http://localhost:5000>, local only) | always |
| `init` | Creates tables, backfills `Datasets/Combined.xlsx` | once per `up` (idempotent) |
| `scheduler` | `ingest-firebase` :05, `score` :10 every hour; `train` Sun 02:00 MYT | always |
| `grafana` | Dashboard, anonymous read-only (<http://localhost:3000>) | always |

## First start (PowerShell)

```powershell
cd FYP-Project
Copy-Item .env.example .env
notepad .env                      # set the three passwords
docker compose up -d --build
docker compose logs -f init       # wait for "building_meter: received=7822 ..."
```

Then train the first model (normally the Sunday job does this):

```powershell
docker compose exec scheduler chiller train --force
```

The first model is promoted automatically **if it passes the gates**. Later
models become `challenger` and wait for you (see "Approving a model").

To see forecasts over the historical data (there is no live building-meter feed yet):

```powershell
docker compose exec scheduler chiller replay --start 2024-11-23 --end 2024-12-08
```

Open <http://localhost:3000> and set the time range to 23 Nov – 7 Dec 2024.

## Everyday commands

```powershell
docker compose exec scheduler chiller score                 # forecast the coming hour now
docker compose exec scheduler chiller ingest-firebase       # pull ESP32 readings now
docker compose exec scheduler chiller ingest-excel /data/Combined.xlsx
docker compose exec scheduler chiller train                 # skips unless >= 7 days of new clean data
docker compose logs -f scheduler                            # job output
```

## Approving a model / rolling back

Each training run's metrics and gate results are in MLflow and in the
dashboard's *Model events* table.

```powershell
docker compose exec scheduler chiller promote 3 --reason "reviewed gates, looks good"
docker compose exec scheduler chiller promote 2 --reason "rollback: v3 worse at peak"
```

`promote` moves the MLflow `champion` alias; the scorer picks it up on its next run.
Set `training.auto_promote: true` in `config/guardrails.yaml` once you trust the gates.

## Live ESP32 feed (optional)

1. Firebase console → Project settings → Service accounts → *Generate new private key*.
   Save it as `deploy/firebase-service-account.json` (git-ignored).
2. In `.env` set `FIREBASE_DB_URL`, `FIREBASE_UID` and
   `FIREBASE_SA_FILE=./deploy/firebase-service-account.json`.
3. `docker compose up -d` — the hourly job starts storing readings as source `esp32`.

To train on the ESP32 feed instead of the building meter, set
`training.source: esp32` once it has at least ~14 weeks of data (6 × 14-day CV folds + the 14-day holdout).

## Reviewing quarantined data

```powershell
docker compose exec db psql -U chiller -c "SELECT ts, reason, payload FROM quarantine WHERE NOT reviewed ORDER BY ts DESC LIMIT 20"
```

Marking a row `reviewed = true` lets the next ingest of that hour validate it again
(for example after re-exporting corrected data). Rows are never deleted.

## Tuning

All thresholds (validation D1–D10, training T1–T7, gates G1–G6, fallback) are in
[`config/guardrails.yaml`](config/guardrails.yaml). Rebuild after editing:
`docker compose up -d --build`.

## Development

```powershell
cd service
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -c constraints.txt -e ".[dev]"
pytest                       # fast tests
```

To run the jobs from a venv against the Compose database, publish the DB port
(add `ports: ["127.0.0.1:5432:5432"]` under `db` in a `docker-compose.override.yml`) and set
`DATABASE_URL=postgresql://chiller:<password>@localhost:5432/chiller` and
`MLFLOW_TRACKING_URI=http://localhost:5000`.
