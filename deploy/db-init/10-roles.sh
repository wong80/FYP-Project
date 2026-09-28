#!/bin/bash
# Runs once, on the database container's first start (empty volume).
# - a separate database for MLflow's tracking store
# - a read-only role for Grafana, covering tables the app creates later
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v grafana_pw="$GRAFANA_DB_PASSWORD" -v owner="$POSTGRES_USER" <<'SQL'
CREATE DATABASE mlflow;
CREATE ROLE grafana_reader LOGIN PASSWORD :'grafana_pw';
GRANT CONNECT ON DATABASE :"DBNAME" TO grafana_reader;
GRANT USAGE ON SCHEMA public TO grafana_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public GRANT SELECT ON TABLES TO grafana_reader;
SQL
