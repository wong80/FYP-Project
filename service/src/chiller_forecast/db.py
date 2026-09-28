"""TimescaleDB access. Timestamps are stored as timestamptz and handed to the
rest of the code as naive Asia/Kuala_Lumpur time (the features are local-time
calendar features, and Malaysia has no daylight saving)."""

from __future__ import annotations

import json
from importlib import resources

import numpy as np
import pandas as pd
from sqlalchemy import Engine, create_engine, text

from .settings import LOCAL_TZ
from .validation import INDEX_NAME, READING_COLUMNS

_QUOTED = ", ".join(f'"{c}"' for c in READING_COLUMNS)


def make_engine(url: str) -> Engine:
    # SQLAlchemy needs the driver named; accept plain postgres:// URLs too.
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
    return create_engine(url, pool_pre_ping=True)


def init_schema(engine: Engine) -> None:
    sql = resources.files(__package__).joinpath("schema.sql").read_text()
    with engine.begin() as conn:
        conn.exec_driver_sql(sql)


def to_local_naive(ts: pd.Series | pd.DatetimeIndex):
    ts = pd.to_datetime(ts, utc=True)
    if isinstance(ts, pd.DatetimeIndex):
        return ts.tz_convert(LOCAL_TZ).tz_localize(None)
    return ts.dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)


def to_aware(ts) -> pd.Timestamp | pd.DatetimeIndex:
    ts = pd.DatetimeIndex(ts) if not isinstance(ts, pd.Timestamp) else ts
    return ts.tz_localize(LOCAL_TZ) if ts.tzinfo is None else ts


def load_readings(engine: Engine, source: str, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> pd.DataFrame:
    """Clean readings in [start, end), indexed by naive local time."""
    sql = f'SELECT ts, {_QUOTED} FROM readings WHERE source = :source'
    params: dict = {"source": source}
    if start is not None:
        sql += " AND ts >= :start"
        params["start"] = to_aware(pd.Timestamp(start)).to_pydatetime()
    if end is not None:
        sql += " AND ts < :end"
        params["end"] = to_aware(pd.Timestamp(end)).to_pydatetime()
    with engine.connect() as conn:
        df = pd.read_sql(text(sql + " ORDER BY ts"), conn, params=params)
    df[INDEX_NAME] = to_local_naive(df.pop("ts"))
    return df.set_index(INDEX_NAME).astype(float)


def latest_reading_ts(engine: Engine, source: str) -> pd.Timestamp | None:
    with engine.connect() as conn:
        ts = conn.execute(text("SELECT max(ts) FROM readings WHERE source = :s"), {"s": source}).scalar()
    return None if ts is None else to_local_naive(pd.DatetimeIndex([ts]))[0]


def existing_timestamps(engine: Engine, source: str, index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Hours already handled: stored as clean, or quarantined and not yet reviewed."""
    if len(index) == 0:
        return index
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT ts FROM readings WHERE source = :s AND ts BETWEEN :a AND :b "
                 "UNION SELECT ts FROM quarantine WHERE source = :s AND NOT reviewed AND ts BETWEEN :a AND :b"),
            {"s": source, "a": to_aware(index.min()).to_pydatetime(), "b": to_aware(index.max()).to_pydatetime()},
        ).scalars().all()
    return to_local_naive(pd.DatetimeIndex(rows)) if rows else pd.DatetimeIndex([])


def insert_readings(engine: Engine, source: str, df: pd.DataFrame) -> int:
    """Insert clean readings; an hour that is already stored is left untouched."""
    if df.empty:
        return 0
    cols = ["source", "ts", *READING_COLUMNS]
    names = ", ".join(f'"{c}"' if c in READING_COLUMNS else c for c in cols)
    values = ", ".join(f":{_param(c)}" for c in cols)
    sql = text(f"INSERT INTO readings ({names}) VALUES ({values}) ON CONFLICT (source, ts) DO NOTHING")
    rows = [
        {"source": source, "ts": ts, **{_param(c): _num(row[c]) for c in READING_COLUMNS}}
        for ts, row in zip(to_aware(df.index).to_pydatetime(), df.to_dict("records"))
    ]
    with engine.begin() as conn:
        result = conn.execute(sql, rows)
    return result.rowcount if result.rowcount is not None and result.rowcount >= 0 else len(rows)


def insert_quarantine(engine: Engine, source: str, df: pd.DataFrame, ingest_run: int | None) -> None:
    if df.empty:
        return
    rows = []
    for ts, row in zip(df.index, df.to_dict("records")):
        reason = row.pop("reason")
        rows.append({
            "source": source,
            "ts": to_aware(pd.Timestamp(ts)).to_pydatetime() if pd.notna(ts) else None,
            "reason": reason,
            "payload": json.dumps({k: _num(v) for k, v in row.items()}),
            "run": ingest_run,
        })
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO quarantine (source, ts, reason, payload, ingest_run) VALUES (:source, :ts, :reason, CAST(:payload AS jsonb), :run)"),
            rows,
        )


def insert_flags(engine: Engine, source: str, flags: pd.DataFrame, ingest_run: int | None) -> None:
    if flags.empty:
        return
    rows = [
        {"source": source, "ts": to_aware(pd.Timestamp(r[INDEX_NAME])).to_pydatetime(), "check": r["check"], "detail": r["detail"], "run": ingest_run}
        for r in flags.to_dict("records")
    ]
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO data_flags (source, ts, check_name, detail, ingest_run) VALUES (:source, :ts, :check, :detail, :run) "
                 "ON CONFLICT (source, ts, check_name) DO NOTHING"),
            rows,
        )


def start_ingest_run(engine: Engine, source: str) -> int:
    with engine.begin() as conn:
        return conn.execute(text("INSERT INTO ingest_runs (source) VALUES (:s) RETURNING id"), {"s": source}).scalar_one()


def finish_ingest_run(engine: Engine, run_id: int, status: str, **counts) -> None:
    allowed = {"rows_received", "rows_new", "rows_clean", "rows_quarantined", "gap_hours", "message"}
    counts = {k: v for k, v in counts.items() if k in allowed}
    sets = ", ".join(f"{k} = :{k}" for k in counts)
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE ingest_runs SET status = :status, finished_at = now(){', ' + sets if sets else ''} WHERE id = :id"),
            {"status": status, "id": run_id, **counts},
        )


def forecast_exists(engine: Engine, source: str, target_ts: pd.Timestamp, roles: tuple[str, ...]) -> bool:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT EXISTS (SELECT 1 FROM forecasts WHERE source = :s AND target_ts = :t AND role = ANY(:roles))"),
            {"s": source, "t": to_aware(target_ts).to_pydatetime(), "roles": list(roles)},
        ).scalar_one()


def insert_forecast(engine: Engine, source: str, target_ts: pd.Timestamp, role: str, model_version: str, predicted_kw: float) -> bool:
    """Write one forecast. An existing forecast for the same hour and role is never replaced."""
    with engine.begin() as conn:
        result = conn.execute(
            text("INSERT INTO forecasts (source, target_ts, role, model_version, predicted_kw) VALUES (:s, :t, :r, :v, :p) "
                 "ON CONFLICT (source, target_ts, role) DO NOTHING"),
            {"s": source, "t": to_aware(target_ts).to_pydatetime(), "r": role, "v": model_version, "p": float(predicted_kw)},
        )
    return result.rowcount == 1


def insert_forecasts(engine: Engine, source: str, role: str, model_version: str, predictions: pd.Series) -> int:
    rows = [
        {"s": source, "t": ts, "r": role, "v": model_version, "p": float(p)}
        for ts, p in zip(to_aware(predictions.index).to_pydatetime(), predictions.to_numpy())
    ]
    if not rows:
        return 0
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO forecasts (source, target_ts, role, model_version, predicted_kw) VALUES (:s, :t, :r, :v, :p) "
                 "ON CONFLICT (source, target_ts, role) DO NOTHING"),
            rows,
        )
    return len(rows)


def record_model_event(engine: Engine, event: str, model_name: str | None, model_version: str | None, detail: dict) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO model_events (event, model_name, model_version, detail) VALUES (:e, :n, :v, CAST(:d AS jsonb))"),
            {"e": event, "n": model_name, "v": model_version, "d": json.dumps(detail, default=_json_default)},
        )


def champion_forecasts(engine: Engine, source: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Forecasts that were shown for [start, end), with the actual reading where one exists."""
    with engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT ts, actual_kw, predicted_kw, role, model_version FROM actual_vs_forecast "
                 "WHERE source = :s AND ts >= :a AND ts < :b ORDER BY ts"),
            conn,
            params={"s": source, "a": to_aware(start).to_pydatetime(), "b": to_aware(end).to_pydatetime()},
        )
    df[INDEX_NAME] = to_local_naive(df.pop("ts"))
    return df.set_index(INDEX_NAME)


def _param(col: str) -> str:
    return col.lower()


def _num(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return str(o)

