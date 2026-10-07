"""Load readings from a source, validate them, and store clean rows / quarantine the rest.

Sources:
* ``excel``    - hourly building-meter export (``Datasets/Combined.xlsx``); used to backfill.
* ``firebase`` - the ESP32's minute readings in Firebase RTDB, averaged to hours.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import requests
from sqlalchemy import Engine

from . import db
from .features import FREQ, TARGET
from .settings import LOCAL_TZ, Env, FirebaseConfig, Guardrails
from .validation import INDEX_NAME, READING_COLUMNS, BatchRejected, validate

log = logging.getLogger(__name__)

CONTEXT_HOURS = 24 * 28  # enough stored history for the stuck-sensor, spike and energy checks


@dataclass
class IngestSummary:
    source: str
    received: int
    new: int
    clean: int
    quarantined: int
    gap_hours: int
    flags: int

    def __str__(self) -> str:
        return (f"{self.source}: received={self.received} new={self.new} clean={self.clean} "
                f"quarantined={self.quarantined} gap_hours={self.gap_hours} flags={self.flags}")


def ingest_frame(engine: Engine, source: str, frame: pd.DataFrame, guardrails: Guardrails,
                 now: pd.Timestamp | None = None) -> IngestSummary:
    """Validate ``frame`` against stored history and write the results."""
    run_id = db.start_ingest_run(engine, source)
    try:
        received = len(frame)
        # Hours already stored are skipped, not re-validated: stored data is never rewritten.
        stored = db.existing_timestamps(engine, source, frame.index)
        frame = frame[~frame.index.isin(stored)]
        if frame.empty:
            db.finish_ingest_run(engine, run_id, "ok", rows_received=received, rows_new=0, rows_clean=0,
                                 rows_quarantined=0, gap_hours=0, message="nothing new")
            return IngestSummary(source, received, 0, 0, 0, 0, 0)

        start = frame.index.min()
        context = db.load_readings(engine, source, start - pd.Timedelta(hours=CONTEXT_HOURS), start)
        result = validate(frame, context=context, now=now, config=guardrails.validation)

        db.insert_readings(engine, source, result.clean)
        db.insert_quarantine(engine, source, result.quarantine, run_id)
        db.insert_flags(engine, source, result.flags, run_id)
        gap_hours = int(result.gaps["missing_hours"].sum()) if len(result.gaps) else 0
        summary = IngestSummary(source, received, len(frame), len(result.clean), len(result.quarantine),
                                gap_hours, len(result.flags))
        db.finish_ingest_run(engine, run_id, "ok", rows_received=received, rows_new=len(frame),
                             rows_clean=len(result.clean), rows_quarantined=len(result.quarantine),
                             gap_hours=gap_hours)
        return summary
    except BatchRejected as exc:
        db.finish_ingest_run(engine, run_id, "rejected", rows_received=len(frame), message=str(exc)[:2000])
        raise
    except Exception as exc:
        db.finish_ingest_run(engine, run_id, "failed", message=repr(exc)[:2000])
        raise


# --- Excel (building meter) -------------------------------------------------

def read_excel(path: str) -> pd.DataFrame:
    df = pd.read_excel(path)
    if INDEX_NAME not in df.columns:
        raise BatchRejected(f"{path}: no '{INDEX_NAME}' column")
    df[INDEX_NAME] = pd.to_datetime(df[INDEX_NAME])
    return df.set_index(INDEX_NAME).sort_index()


# --- Firebase (ESP32) -------------------------------------------------------

_FIREBASE_FIELDS = {
    "voltage1": "voltageA", "voltage2": "voltageB", "voltage3": "voltageC",
    "current1": "currentA", "current2": "currentB", "current3": "currentC",
    "power1": "activePowerA", "power2": "activePowerB", "power3": "activePowerC",
}


def fetch_firebase(env: Env) -> dict | list | None:
    """Download ``/UsersData/<uid>/readings`` with a service-account token."""
    if not (env.firebase_db_url and env.firebase_uid):
        raise RuntimeError("FIREBASE_DB_URL and FIREBASE_UID must be set for the firebase source")
    import google.auth.transport.requests
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        env.google_credentials,
        scopes=["https://www.googleapis.com/auth/firebase.database", "https://www.googleapis.com/auth/userinfo.email"],
    )
    creds.refresh(google.auth.transport.requests.Request())
    url = f"{env.firebase_db_url.rstrip('/')}/UsersData/{env.firebase_uid}/readings.json"
    resp = requests.get(url, params={"access_token": creds.token}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def firebase_to_hourly(payload: dict | list | None, config: FirebaseConfig, now: pd.Timestamp) -> pd.DataFrame:
    """Turn raw ESP32 minute readings into hourly rows in the readings schema.

    * Timestamps come from the ESP32's RTC as ``d/m/Y H:M:S`` local time.
    * Values are averaged per hour; an hour with fewer than
      ``min_samples_per_hour`` readings is dropped (left as a gap), as is the
      current, still-filling hour.
    * The ESP32 has no energy counter or line voltages; those stay empty.
    """
    records = list(payload.values()) if isinstance(payload, dict) else [r for r in (payload or []) if r]
    empty = pd.DataFrame(columns=list(READING_COLUMNS), index=pd.DatetimeIndex([], name=INDEX_NAME), dtype=float)
    if not records:
        return empty

    raw = pd.DataFrame.from_records(records)
    ts = pd.to_datetime(raw.get("timestamp"), format="%d/%m/%Y %H:%M:%S", errors="coerce")
    values = raw.reindex(columns=list(_FIREBASE_FIELDS)).apply(pd.to_numeric, errors="coerce").rename(columns=_FIREBASE_FIELDS)
    values.index = ts
    values = values[values.index.notna()]
    values = values[~values.index.duplicated(keep="first")]
    for col in ("activePowerA", "activePowerB", "activePowerC"):
        values[col] = values[col] / config.power_unit_divisor

    current_hour = pd.Timestamp(now).floor(FREQ)
    values = values[values.index < current_hour]
    if values.empty:
        return empty

    hourly = values.resample(FREQ).mean()
    counts = values.notna().all(axis=1).resample(FREQ).sum()
    hourly = hourly[counts >= config.min_samples_per_hour]
    hourly[TARGET] = hourly[["activePowerA", "activePowerB", "activePowerC"]].sum(axis=1, min_count=3)
    for col in READING_COLUMNS:
        if col not in hourly.columns:
            hourly[col] = np.nan
    hourly.index.name = INDEX_NAME
    return hourly[list(READING_COLUMNS)]


def now_local() -> pd.Timestamp:
    return pd.Timestamp.now(tz=LOCAL_TZ).tz_localize(None)
