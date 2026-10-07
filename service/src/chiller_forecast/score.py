"""Hourly scorer: forecast the next hour with the champion (and log the challenger).

Rules:
* Only the coming hour is forecast. Past hours are never back-filled with
  forecasts, so the dashboard's error figures are honest.
* If the newest reading is older than ``stale_after_hours``, the model's
  recent-history features are unreliable, so the shown forecast falls back to
  seasonal-naive (the same hour last week) and is labelled ``fallback``.
* A challenger, if one is registered, is scored too but never shown (shadow).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import mlflow
import pandas as pd
from mlflow import MlflowClient
from sqlalchemy import Engine

from . import db
from .features import FEATURES, MAX_LOOKBACK_H, TARGET, build_features, features_for_hour
from .ingest import now_local
from .model import load
from .settings import Env, Guardrails
from .train import CHALLENGER, CHAMPION, _alias_version

log = logging.getLogger(__name__)

_model_cache: dict[str, object] = {}


@dataclass
class ScoreOutcome:
    target_ts: pd.Timestamp
    written: dict[str, float]
    note: str = ""


def score(engine: Engine, env: Env, guardrails: Guardrails, now: pd.Timestamp | None = None) -> ScoreOutcome:
    source = guardrails.training.source
    now = now_local() if now is None else pd.Timestamp(now)
    target = now.floor("h") + pd.Timedelta(hours=1)
    history = db.load_readings(engine, source, start=target - pd.Timedelta(hours=guardrails.scoring.history_hours), end=target)
    written: dict[str, float] = {}

    if db.forecast_exists(engine, source, target, ("champion", "fallback")):
        return ScoreOutcome(target, written, "forecast for this hour already issued")

    mlflow.set_tracking_uri(env.mlflow_tracking_uri)
    client = MlflowClient()
    champion = _alias_version(client, env.model_name, CHAMPION)
    challenger = _alias_version(client, env.model_name, CHALLENGER)

    latest = history.index.max() if len(history) else None
    stale = latest is None or latest < target - pd.Timedelta(hours=1 + guardrails.scoring.stale_after_hours)

    if champion is None or stale:
        naive = _seasonal_naive(engine, source, target)
        note = "no champion model" if champion is None else f"data stale (latest reading {latest})"
        if naive is not None:
            db.insert_forecast(engine, source, target, "fallback", "seasonal_naive", naive)
            written["fallback"] = naive
        else:
            note += "; no reading one week earlier either, nothing issued"
        log.warning("fallback forecast for %s: %s", target, note)
        return ScoreOutcome(target, written, note)

    X = features_for_hour(history, target)
    for role, version in ((CHAMPION, champion), (CHALLENGER, challenger)):
        if version is None:
            continue
        try:
            pred = max(0.0, float(_model(env, version.version).predict(X)[0]))
        except Exception:
            if role == CHALLENGER:
                log.exception("challenger v%s failed to score", version.version)
                continue
            raise
        db.insert_forecast(engine, source, target, role, str(version.version), pred)
        written[role] = pred
    return ScoreOutcome(target, written)


def _model(env: Env, version: str):
    if version not in _model_cache:
        _model_cache[version] = load(f"models:/{env.model_name}/{version}")
    return _model_cache[version]


def _seasonal_naive(engine: Engine, source: str, target: pd.Timestamp) -> float | None:
    week_ago = target - pd.Timedelta(days=7)
    row = db.load_readings(engine, source, start=week_ago, end=week_ago + pd.Timedelta(hours=1))
    return float(row[TARGET].iloc[0]) if len(row) else None


def replay(engine: Engine, env: Env, guardrails: Guardrails, start: pd.Timestamp, end: pd.Timestamp,
           version: str | None = None) -> int:
    """Simulate live scoring over past hours [start, end) and store them as role ``replay``.

    Each hour's features use only readings before that hour (the same rule the
    live scorer follows), so this shows how the model *would* have done. Replay
    rows are kept apart from real forecasts so they can't be mistaken for them.
    A model is only fair on hours it never trained on, so hours before the
    model's ``holdout_start`` tag are skipped.
    """
    source = guardrails.training.source
    mlflow.set_tracking_uri(env.mlflow_tracking_uri)
    client = MlflowClient()
    mv = client.get_model_version(env.model_name, version) if version else _alias_version(client, env.model_name, CHAMPION)
    if mv is None:
        raise RuntimeError("no champion model to replay")
    holdout_start = pd.Timestamp(mv.tags.get("holdout_start", start))
    start = max(pd.Timestamp(start), holdout_start)
    history = db.load_readings(engine, source, start=start - pd.Timedelta(hours=MAX_LOOKBACK_H), end=end)
    feats = build_features(history)
    feats = feats[(feats.index >= start) & (feats.index < end)]
    if feats.empty:
        return 0
    preds = _model(env, mv.version).predict(feats[FEATURES]).clip(min=0)
    return db.insert_forecasts(engine, source, "replay", str(mv.version), pd.Series(preds, index=feats.index))
