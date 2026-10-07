"""Runtime settings: connection details from the environment, thresholds from guardrails.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from .validation import ValidationConfig

DEFAULT_GUARDRAILS = Path(__file__).resolve().parents[2] / "config" / "guardrails.yaml"
LOCAL_TZ = "Asia/Kuala_Lumpur"


@dataclass(frozen=True)
class TrainingConfig:
    source: str = "building_meter"
    holdout_hours: int = 336            # newest 14 days, never trained on
    cv_folds: int = 5
    cv_fold_hours: int = 336            # each time-ordered validation fold = 14 days
    max_history_days: int = 730         # T5: expanding window capped at 24 months
    min_new_hours: int = 168            # T4: retrain only with >= 7 days of new clean data
    time_limit_s: int = 600             # T6
    algorithms: tuple[str, ...] = ("LightGBM", "Xgboost", "CatBoost", "Random Forest", "Extra Trees")
    mode: str = "Compete"
    random_state: int = 42
    auto_promote_first_model: bool = True
    auto_promote: bool = False          # human-approved promotion until gates have earned trust


@dataclass(frozen=True)
class GateConfig:
    min_improvement: float = 0.02       # G1
    max_vs_naive: float = 0.8           # G2
    min_r2: float = 0.80                # G3
    max_segment_regression: float = 1.10  # G4
    max_abs_bias_kw: float = 10.0       # G5
    max_pred_vs_hist_max: float = 1.2   # G6


@dataclass(frozen=True)
class ScoringConfig:
    stale_after_hours: int = 2          # M4: older than this -> seasonal-naive fallback
    history_hours: int = 400            # enough for the longest lag (336 h) plus margin


@dataclass(frozen=True)
class FirebaseConfig:
    min_samples_per_hour: int = 30      # ESP32 sends ~1/min; fewer -> hour is incomplete
    power_unit_divisor: float = 1000.0  # PZEM reports W; readings table stores kW


@dataclass(frozen=True)
class Guardrails:
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    training: TrainingConfig = field(default_factory=TrainingConfig)
    gates: GateConfig = field(default_factory=GateConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    firebase: FirebaseConfig = field(default_factory=FirebaseConfig)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Guardrails":
        path = Path(path or os.environ.get("GUARDRAILS_PATH", DEFAULT_GUARDRAILS))
        raw = yaml.safe_load(path.read_text()) or {}
        return cls(
            validation=ValidationConfig.from_dict(raw.get("validation", {})),
            training=_build(TrainingConfig, raw.get("training", {})),
            gates=_build(GateConfig, raw.get("gates", {})),
            scoring=_build(ScoringConfig, raw.get("scoring", {})),
            firebase=_build(FirebaseConfig, raw.get("firebase", {})),
        )


@dataclass(frozen=True)
class Env:
    database_url: str
    mlflow_tracking_uri: str
    model_name: str
    firebase_db_url: str | None
    firebase_uid: str | None
    google_credentials: str | None

    @classmethod
    def load(cls) -> "Env":
        return cls(
            database_url=_required("DATABASE_URL"),
            mlflow_tracking_uri=os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
            model_name=os.environ.get("MODEL_NAME", "chiller-power"),
            firebase_db_url=os.environ.get("FIREBASE_DB_URL"),
            firebase_uid=os.environ.get("FIREBASE_UID"),
            google_credentials=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        )


def _build(cls, values: dict):
    known = {f.name for f in fields(cls)}
    unknown = set(values) - known
    if unknown:
        raise ValueError(f"unknown {cls.__name__} settings: {sorted(unknown)}")
    return cls(**{k: tuple(v) if isinstance(v, list) else v for k, v in values.items()})


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"environment variable {name} is not set")
    return value
