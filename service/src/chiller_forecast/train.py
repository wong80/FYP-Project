"""Weekly training job: MLJAR with time-ordered folds, holdout gates, MLflow registry.

Split (newest data on the right):

    |<------------- training part ------------->|<-- holdout (14 d) -->|
    | fold1 | fold2 | ... time-ordered CV folds  |  never trained on    |

MLJAR picks and ensembles models using only the CV folds (T1). The holdout is
then used once, for the promotion gates, and the champion is scored on the same
holdout so the comparison is like-for-like.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import asdict, dataclass

import mlflow
import numpy as np
import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from sklearn.model_selection import TimeSeriesSplit
from sqlalchemy import Engine

from . import db
from .features import FEATURES, TARGET, build_features, trainable_rows
from .gates import Metrics, all_passed, evaluate, run_gates
from .model import load, log_mljar_model
from .settings import Env, Guardrails
from .validation import completeness

log = logging.getLogger(__name__)

EXPERIMENT = "chiller-forecast"
CHAMPION = "champion"
CHALLENGER = "challenger"


@dataclass
class TrainOutcome:
    status: str                      # promoted | challenger | rejected | skipped
    reason: str
    version: str | None = None
    metrics: dict | None = None
    gates: list | None = None


def train(engine: Engine, env: Env, guardrails: Guardrails, *, force: bool = False) -> TrainOutcome:
    cfg = guardrails.training
    mlflow.set_tracking_uri(env.mlflow_tracking_uri)
    client = MlflowClient()
    champion = _alias_version(client, env.model_name, CHAMPION)

    latest = db.latest_reading_ts(engine, cfg.source)
    if latest is None:
        return _skip(engine, env, f"no readings for source '{cfg.source}'")
    end = latest + pd.Timedelta(hours=1)

    # T4 - enough new data since the champion was trained?
    if champion is not None and not force:
        data_end = pd.Timestamp(champion.tags.get("data_end", "1970-01-01"))
        new_hours = len(db.load_readings(engine, cfg.source, start=data_end))
        if new_hours < cfg.min_new_hours:
            return _skip(engine, env, f"only {new_hours} new clean hours since {data_end} (< {cfg.min_new_hours})")

    # T5 - expanding window, capped
    readings = db.load_readings(engine, cfg.source, start=end - pd.Timedelta(days=cfg.max_history_days), end=end)
    min_rows = (cfg.cv_folds + 1) * cfg.cv_fold_hours + cfg.holdout_hours
    if len(readings) < min_rows:
        return _skip(engine, env, f"{len(readings)} clean hours, need at least {min_rows}")

    # D10 - the window must be mostly complete
    comp = completeness(readings.index, readings.index.min(), end)
    if comp < guardrails.validation.min_completeness:
        return _skip(engine, env, f"training window {comp:.1%} complete (< {guardrails.validation.min_completeness:.0%})")

    rows = trainable_rows(build_features(readings))
    holdout_start = end - pd.Timedelta(hours=cfg.holdout_hours)
    train_df = rows[rows.index < holdout_start]
    hold_df = rows[rows.index >= holdout_start]
    X, y = train_df[FEATURES], train_df[TARGET]
    cv = list(TimeSeriesSplit(n_splits=cfg.cv_folds, test_size=cfg.cv_fold_hours).split(X))

    mlflow.set_experiment(EXPERIMENT)
    with tempfile.TemporaryDirectory() as tmp, mlflow.start_run(run_name=f"train-{latest:%Y%m%d-%H}") as run:
        results_path = os.path.join(tmp, "mljar")
        automl = _fit(X, y, cv, results_path, guardrails)

        metrics = evaluate(hold_df[TARGET], automl.predict(hold_df[FEATURES]).clip(min=0), hold_df["lag_7d"])  # as served (model.py)
        champ_metrics = _score_champion(env, champion, hold_df) if champion is not None else None
        gates = run_gates(metrics, champ_metrics, float(readings[TARGET].max()), guardrails.gates)

        mlflow.log_params({
            "source": cfg.source, "mode": cfg.mode, "algorithms": ",".join(cfg.algorithms),
            "time_limit_s": cfg.time_limit_s, "random_state": cfg.random_state, "cv_folds": cfg.cv_folds,
            "cv_fold_hours": cfg.cv_fold_hours, "holdout_hours": cfg.holdout_hours, "n_features": len(FEATURES),
        })
        mlflow.log_metrics({k: v for k, v in metrics.flat("holdout_").items() if np.isfinite(v)})
        if champ_metrics is not None:
            mlflow.log_metrics({k: v for k, v in champ_metrics.flat("champion_holdout_").items() if np.isfinite(v)})
        mlflow.log_dict({"features": FEATURES}, "features.json")
        mlflow.log_dict({"gates": [asdict(g) for g in gates]}, "gates.json")
        mlflow.log_text(automl.get_leaderboard().to_csv(index=False), "leaderboard.csv")

        tags = {
            "data_source": cfg.source,
            "data_start": str(readings.index.min()),
            "data_end": str(end),
            "holdout_start": str(holdout_start),
            "train_rows": str(len(train_df)),
            "holdout_rows": str(len(hold_df)),
            "data_sha256": _data_hash(readings),
            "git_sha": os.environ.get("GIT_SHA", "unknown"),
            "mljar_version": _mljar_version(),
            "best_model": str(automl._best_model.get_name()),
            "holdout_mae": f"{metrics.mae:.4f}",
            "gates_passed": str(all_passed(gates)).lower(),
        }
        mlflow.set_tags(tags)
        info = log_mljar_model(results_path, env.model_name)
        version = str(info.registered_model_version)
        for k, v in tags.items():
            client.set_model_version_tag(env.model_name, version, k, v)

    return _decide(engine, env, client, guardrails, version, champion, metrics, gates, run.info.run_id)


def promote(engine: Engine, env: Env, version: str, reason: str = "manual") -> None:
    """Make ``version`` the live model (also how you roll back: promote an older version)."""
    mlflow.set_tracking_uri(env.mlflow_tracking_uri)
    client = MlflowClient()
    client.get_model_version(env.model_name, version)  # raises if it doesn't exist
    previous = _alias_version(client, env.model_name, CHAMPION)
    client.set_registered_model_alias(env.model_name, CHAMPION, version)
    challenger = _alias_version(client, env.model_name, CHALLENGER)
    if challenger is not None and challenger.version == version:
        client.delete_registered_model_alias(env.model_name, CHALLENGER)
    db.record_model_event(engine, "promoted", env.model_name, version,
                          {"reason": reason, "previous_champion": previous.version if previous else None})
    log.info("promoted %s v%s (previous: %s)", env.model_name, version, previous.version if previous else None)


def _decide(engine, env, client, guardrails, version, champion, metrics: Metrics, gates, run_id) -> TrainOutcome:
    cfg = guardrails.training
    detail = {"run_id": run_id, "metrics": metrics.flat(), "gates": [asdict(g) for g in gates]}
    if not all_passed(gates):
        failed = [g.name for g in gates if not g.passed]
        db.record_model_event(engine, "rejected", env.model_name, version, {**detail, "failed": failed})
        return TrainOutcome("rejected", f"failed gates {failed}", version, metrics.flat(), detail["gates"])

    first = champion is None
    if (first and cfg.auto_promote_first_model) or (not first and cfg.auto_promote):
        db.record_model_event(engine, "trained", env.model_name, version, detail)
        promote(engine, env, version, reason="first model" if first else "auto: all gates passed")
        return TrainOutcome("promoted", "all gates passed", version, metrics.flat(), detail["gates"])

    client.set_registered_model_alias(env.model_name, CHALLENGER, version)
    db.record_model_event(engine, "trained", env.model_name, version, {**detail, "awaiting_approval": True})
    return TrainOutcome("challenger", "all gates passed; awaiting approval (`promote`)", version,
                        metrics.flat(), detail["gates"])


def _fit(X: pd.DataFrame, y: pd.Series, cv: list, results_path: str, guardrails: Guardrails):
    from supervised import AutoML

    cfg = guardrails.training
    automl = AutoML(
        results_path=results_path,
        mode=cfg.mode,
        ml_task="regression",
        eval_metric="rmse",
        algorithms=list(cfg.algorithms),
        total_time_limit=cfg.time_limit_s,
        validation_strategy={"validation_type": "custom"},  # T1: our time-ordered folds, not shuffled k-fold
        train_ensemble=True,
        stack_models=False,   # stacking re-uses out-of-fold predictions, which assumes shuffled folds
        explain_level=0,
        golden_features=False,
        features_selection=False,
        random_state=cfg.random_state,
        n_jobs=-1,
        verbose=0,
    )
    automl.fit(X, y, cv=cv)
    return automl


def _score_champion(env: Env, champion, hold_df: pd.DataFrame) -> Metrics | None:
    try:
        model = load(f"models:/{env.model_name}/{champion.version}")
        return evaluate(hold_df[TARGET], model.predict(hold_df[FEATURES]), hold_df["lag_7d"])
    except Exception:  # a broken champion must not block a replacement; the gates still apply
        log.exception("could not score champion v%s on the holdout", champion.version)
        return None


def _alias_version(client: MlflowClient, name: str, alias: str):
    try:
        return client.get_model_version_by_alias(name, alias)
    except MlflowException:
        return None


def _skip(engine: Engine, env: Env, reason: str) -> TrainOutcome:
    log.info("training skipped: %s", reason)
    db.record_model_event(engine, "skipped", env.model_name, None, {"reason": reason})
    return TrainOutcome("skipped", reason)


def _data_hash(df: pd.DataFrame) -> str:
    hashed = pd.util.hash_pandas_object(df, index=True).to_numpy()
    return hashlib.sha256(hashed.tobytes()).hexdigest()


def _mljar_version() -> str:
    from importlib.metadata import version

    return version("mljar-supervised")


def outcome_json(outcome: TrainOutcome) -> str:
    return json.dumps(asdict(outcome), indent=2, default=str)
