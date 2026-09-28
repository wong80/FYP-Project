"""Feature engineering shared by the trainer and the scorer (guardrail T2).

Ported from ``create_enhanced_features`` in
``Jupyter Notebooks/MLJAR_AutoML_Improved.ipynb``. The feature *definitions* are
unchanged; two things differ on purpose:

* Everything is computed on a regular hourly grid. The notebook used row-based
  ``shift``/``rolling``, which silently spans a gap (the row "one before" may be
  four hours earlier). Here a missing hour stays missing, so windows are always
  measured in real hours.
* The target is never filled in. Missing hours only reduce ``min_periods``-style
  windows; they are not imputed (guardrail D9).

Every feature at time ``t`` uses data from strictly before ``t`` (guardrail T3),
so a row can be scored before its own reading arrives.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TARGET = "activePowerT"
FREQ = "h"

FEATURES: list[str] = [
    # Calendar
    "hour", "dayofweek", "quarter", "month", "dayofyear", "dayofmonth", "weekofyear",
    # Cyclical encodings
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    # Operating-pattern flags (chiller runs ~09:00-23:00, lighter at weekends)
    "is_weekend", "is_working_hours",
    # Target lags
    "lag_24h", "lag_7d", "lag_8d", "lag_9d", "lag_10d", "lag_14d",
    # Phase A lags
    "activePowerA_lag1", "currentA_lag1", "activePowerA_lag2", "currentA_lag2",
    # Rolling statistics of the target, ending one hour before t
    "rolling_mean_24h", "rolling_std_24h", "rolling_mean_7d", "rolling_std_7d",
    # Same-hour change: yesterday vs last week
    "diff_24h",
]

# Raw columns the features read. Anything else in the input is ignored.
REQUIRED_COLUMNS: tuple[str, ...] = (TARGET, "activePowerA", "currentA")

_TARGET_LAGS_H = {"lag_24h": 24, "lag_7d": 168, "lag_8d": 192, "lag_9d": 216, "lag_10d": 240, "lag_14d": 336}
_PHASE_A_LAGS_H = {
    "activePowerA_lag1": ("activePowerA", 168),
    "currentA_lag1": ("currentA", 168),
    "activePowerA_lag2": ("activePowerA", 336),
    "currentA_lag2": ("currentA", 336),
}

# Longest look-back any feature needs. Callers building features for recent
# hours must pass at least this much history in front of them.
MAX_LOOKBACK_H = max(max(_TARGET_LAGS_H.values()), max(h for _, h in _PHASE_A_LAGS_H.values()), 168 + 1)


def to_hourly_grid(df: pd.DataFrame) -> pd.DataFrame:
    """Reindex onto a complete hourly index. Missing hours become NaN rows."""
    _check_index(df)
    if df.empty:
        return df.copy()
    full = pd.date_range(df.index.min(), df.index.max(), freq=FREQ, name=df.index.name)
    return df.reindex(full)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Return ``df`` on an hourly grid with every column in ``FEATURES`` added.

    ``df`` must have a sorted, unique, hour-aligned ``DatetimeIndex`` and the
    columns in ``REQUIRED_COLUMNS``. Rows inserted for missing hours keep a NaN
    target; drop them with ``trainable_rows`` before training.
    """
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(f"build_features: missing columns {missing}")

    out = to_hourly_grid(df)
    idx = out.index
    y = out[TARGET].astype(float)

    hour = idx.hour
    dow = idx.dayofweek
    month = idx.month
    out["hour"] = hour
    out["dayofweek"] = dow
    out["quarter"] = idx.quarter
    out["month"] = month
    out["dayofyear"] = idx.dayofyear
    out["dayofmonth"] = idx.day
    out["weekofyear"] = idx.isocalendar().week.astype(int).to_numpy()

    out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
    out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    out["dow_sin"] = np.sin(2 * np.pi * dow / 7)
    out["dow_cos"] = np.cos(2 * np.pi * dow / 7)
    out["month_sin"] = np.sin(2 * np.pi * month / 12)
    out["month_cos"] = np.cos(2 * np.pi * month / 12)

    out["is_weekend"] = (dow >= 5).astype(int)
    out["is_working_hours"] = ((hour >= 9) & (hour <= 22)).astype(int)

    # On a regular grid, shift(n) is exactly "n hours earlier".
    for name, hours in _TARGET_LAGS_H.items():
        out[name] = y.shift(hours)
    for name, (col, hours) in _PHASE_A_LAGS_H.items():
        out[name] = out[col].astype(float).shift(hours)

    past = y.shift(1)
    out["rolling_mean_24h"] = past.rolling(24, min_periods=1).mean()
    out["rolling_std_24h"] = past.rolling(24, min_periods=2).std()
    out["rolling_mean_7d"] = past.rolling(168, min_periods=1).mean()
    out["rolling_std_7d"] = past.rolling(168, min_periods=2).std()

    # Name kept from the notebook for model compatibility; it is the change in
    # the same hour between last week and yesterday.
    out["diff_24h"] = out["lag_24h"] - out["lag_7d"]

    return out


def trainable_rows(features: pd.DataFrame) -> pd.DataFrame:
    """Rows with a real (observed) target. Never train on filled-in targets."""
    return features[features[TARGET].notna()]


def features_for_hour(history: pd.DataFrame, ts: pd.Timestamp) -> pd.DataFrame:
    """Feature row for hour ``ts`` using only ``history`` strictly before ``ts``.

    This is what the scorer calls: the reading for ``ts`` doesn't exist yet, so
    a placeholder row with a NaN target is appended and featurised.
    """
    ts = pd.Timestamp(ts)
    if ts != ts.floor(FREQ):
        raise ValueError(f"features_for_hour: {ts} is not aligned to the hour")
    past = history[history.index < ts]
    if past.empty:
        raise ValueError("features_for_hour: no history before the requested hour")
    placeholder = pd.DataFrame(index=pd.DatetimeIndex([ts], name=history.index.name), columns=list(REQUIRED_COLUMNS), dtype=float)
    window = past.loc[past.index >= ts - pd.Timedelta(hours=MAX_LOOKBACK_H), list(REQUIRED_COLUMNS)]
    feats = build_features(pd.concat([window, placeholder]))
    return feats.loc[[ts], FEATURES]


def _check_index(df: pd.DataFrame) -> None:
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("expected a DatetimeIndex")
    if df.index.has_duplicates:
        raise ValueError("index has duplicate timestamps")
    if not df.index.is_monotonic_increasing:
        raise ValueError("index is not sorted")
    if len(df.index) and not (df.index == df.index.floor(FREQ)).all():
        raise ValueError("index has timestamps not aligned to the hour")
