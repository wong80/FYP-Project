"""Data guardrails D1-D10 (DESIGN.md §4.1): decide which readings may be stored and trained on.

``validate`` splits an incoming batch into:

* ``clean``      - rows that passed every hard check,
* ``quarantine`` - rows that failed one, with a ``reason`` column (never deleted),
* ``flags``      - soft findings on clean rows (logged, not blocking),
* ``gaps``       - missing hours (recorded, never filled in).

Checks that need earlier readings (energy counter, stuck sensor, spikes, gaps)
look at ``context``: already-stored clean rows just before the batch. Context
rows are only used as reference and are never returned.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pandera.pandas as pa
import yaml

from .features import FREQ, TARGET

INDEX_NAME = "dateTime"
PHASES = ("A", "B", "C")
PHASE_VOLTAGES = tuple(f"voltage{p}" for p in PHASES)
PHASE_CURRENTS = tuple(f"current{p}" for p in PHASES)
PHASE_POWERS = tuple(f"activePower{p}" for p in PHASES)
LINE_VOLTAGES = ("voltageL12", "voltageL23", "voltageL31")
ENERGY = "importActiveEnergyT"

# Every source must provide these on every row.
REQUIRED_VALUES = (*PHASE_VOLTAGES, *PHASE_CURRENTS, *PHASE_POWERS, TARGET)
# Present as columns, but a source may not measure them (the ESP32 has neither).
OPTIONAL_VALUES = (ENERGY, *LINE_VOLTAGES)
READING_COLUMNS = (ENERGY, *PHASE_CURRENTS, *PHASE_VOLTAGES, TARGET, *PHASE_POWERS, *LINE_VOLTAGES)


@dataclass(frozen=True)
class ValidationConfig:
    future_tolerance_minutes: float = 5
    phase_voltage_v: tuple[float, float] = (200, 270)
    line_voltage_v: tuple[float, float] = (350, 470)
    current_a: tuple[float, float] = (0, 2000)
    active_power_total_kw: tuple[float, float] = (0, 1000)
    phase_sum_tolerance_kw: float = 2.0
    apparent_power_slack: float = 1.05
    energy_rate_rel_tolerance: float = 1.0
    energy_rate_abs_tolerance_kwh: float = 5.0
    stuck_run_hours: int = 6
    spike_robust_z: float = 6.0
    spike_min_samples: int = 4
    min_completeness: float = 0.90

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ValidationConfig":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls.from_dict(raw.get("validation", {}))

    @classmethod
    def from_dict(cls, values: dict) -> "ValidationConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(values) - known
        if unknown:
            raise ValueError(f"unknown validation settings: {sorted(unknown)}")
        return cls(**{k: tuple(v) if isinstance(v, list) else v for k, v in values.items()})


@dataclass
class ValidationResult:
    clean: pd.DataFrame
    quarantine: pd.DataFrame
    flags: pd.DataFrame
    gaps: pd.DataFrame

    @property
    def quarantine_rate(self) -> float:
        total = len(self.clean) + len(self.quarantine)
        return len(self.quarantine) / total if total else 0.0


class BatchRejected(ValueError):
    """D1: the batch as a whole is malformed (missing columns, wrong types)."""


_BATCH_SCHEMA = pa.DataFrameSchema(
    {col: pa.Column(float, nullable=True, coerce=True) for col in READING_COLUMNS},
    index=pa.Index(pa.DateTime, name=INDEX_NAME),
    strict="filter",
)


def validate(
    batch: pd.DataFrame,
    *,
    context: pd.DataFrame | None = None,
    now: datetime | pd.Timestamp | None = None,
    config: ValidationConfig = ValidationConfig(),
) -> ValidationResult:
    """Run D1-D9 on ``batch``. Timestamps are naive local time (Asia/Kuala_Lumpur)."""
    df = _check_schema(batch)  # D1
    now = pd.Timestamp.now(tz="Asia/Kuala_Lumpur").tz_localize(None) if now is None else pd.Timestamp(now)
    context = _check_schema(context) if context is not None and len(context) else df.iloc[0:0]
    context = context[context.index < df.index.min()] if len(df) else context

    reasons: dict[str, pd.Series] = {}

    # D2 - timestamps
    reasons["future_timestamp"] = pd.Series(df.index > now + pd.Timedelta(minutes=config.future_tolerance_minutes), index=df.index)
    reasons["not_hour_aligned"] = pd.Series(df.index != df.index.floor(FREQ), index=df.index)
    df, conflicting = _resolve_duplicates(df)
    for name in list(reasons):
        reasons[name] = _align(reasons[name], df)

    # Missing required measurements: can't be checked, so can't be trusted.
    reasons["missing_value"] = df[list(REQUIRED_VALUES)].isna().any(axis=1)

    # D3 - physical ranges (NaN in an optional column is not a failure)
    reasons["phase_voltage_out_of_range"] = _outside(df[list(PHASE_VOLTAGES)], config.phase_voltage_v)
    reasons["line_voltage_out_of_range"] = _outside(df[list(LINE_VOLTAGES)], config.line_voltage_v)
    reasons["current_out_of_range"] = _outside(df[list(PHASE_CURRENTS)], config.current_a)
    reasons["power_out_of_range"] = _outside(df[[TARGET]], config.active_power_total_kw)

    # D4 - total equals the sum of phases
    phase_sum = df[list(PHASE_POWERS)].sum(axis=1, min_count=3)
    reasons["phase_sum_mismatch"] = (df[TARGET] - phase_sum).abs() > config.phase_sum_tolerance_kw

    # D5 - real power can't exceed apparent power (V * I)
    over = pd.Series(False, index=df.index)
    for v, i, p in zip(PHASE_VOLTAGES, PHASE_CURRENTS, PHASE_POWERS):
        over |= df[p] > df[v] * df[i] / 1000 * config.apparent_power_slack
    reasons["power_exceeds_apparent"] = over

    # D6 (hard part) - the energy counter never goes backwards
    prev_energy = pd.concat([context[ENERGY], df[ENERGY]]).ffill().shift(1).reindex(df.index)
    reasons["energy_counter_decreased"] = (df[ENERGY] < prev_energy).fillna(False)

    # D7 - sensor stuck on one value
    reasons["stuck_sensor"] = _stuck_runs(context[TARGET], df[TARGET], config.stuck_run_hours)

    failed = pd.DataFrame(reasons).fillna(False).astype(bool)
    bad = failed.any(axis=1)
    reason_text = failed.apply(lambda row: ";".join(failed.columns[row.to_numpy()]), axis=1)

    quarantine = df[bad].assign(reason=reason_text[bad])
    if len(conflicting):
        quarantine = pd.concat([quarantine, conflicting.assign(reason="conflicting_duplicate")]).sort_index()
    clean = df[~bad]

    flags = pd.concat([_energy_rate_flags(context, clean, config), _spike_flags(context, clean, config)])
    flags = flags.sort_values(INDEX_NAME).reset_index(drop=True)
    return ValidationResult(clean=clean, quarantine=quarantine, flags=flags, gaps=find_gaps(context, clean))


def completeness(index: pd.DatetimeIndex, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """D10: share of hours in [start, end) that have a clean reading."""
    start, end = pd.Timestamp(start).ceil(FREQ), pd.Timestamp(end)
    if end <= start:
        return 0.0
    expected = pd.date_range(start, end, freq=FREQ, inclusive="left")
    return float(expected.isin(index).sum()) / len(expected)


def find_gaps(context: pd.DataFrame, clean: pd.DataFrame) -> pd.DataFrame:
    """D9: runs of missing hours in ``clean`` (and between the last context row and it)."""
    cols = ["gap_start", "gap_end", "missing_hours"]
    if clean.empty:
        return pd.DataFrame(columns=cols)
    idx = clean.index
    if len(context):
        idx = idx.union(pd.DatetimeIndex([context.index.max()]))
    step = idx.to_series().diff()
    rows = [
        (prev + pd.Timedelta(hours=1), cur - pd.Timedelta(hours=1), int(delta / pd.Timedelta(hours=1)) - 1)
        for prev, cur, delta in zip(idx[:-1], idx[1:], step.iloc[1:])
        if delta > pd.Timedelta(hours=1)
    ]
    return pd.DataFrame(rows, columns=cols)


def _check_schema(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in READING_COLUMNS if c not in df.columns]
    if missing:
        raise BatchRejected(f"missing columns: {missing}")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise BatchRejected("index must be a DatetimeIndex of reading timestamps")
    if df.index.tz is not None:
        raise BatchRejected("timestamps must be naive local time (Asia/Kuala_Lumpur)")
    try:
        out = _BATCH_SCHEMA.validate(df.rename_axis(INDEX_NAME), lazy=True)
    except (pa.errors.SchemaErrors, pa.errors.SchemaError) as exc:
        raise BatchRejected(str(exc)) from exc
    return out.sort_index(kind="stable")


def _resolve_duplicates(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Identical re-sends collapse to one row; disagreeing copies are all quarantined."""
    if not df.index.has_duplicates:
        return df, df.iloc[0:0]
    exact = df.reset_index().duplicated(keep="first").to_numpy()
    df = df[~exact]
    dup = df.index.duplicated(keep=False)
    return df[~dup], df[dup]


def _align(mask: pd.Series, df: pd.DataFrame) -> pd.Series:
    mask = mask[~mask.index.duplicated(keep="first")]
    return mask.reindex(df.index, fill_value=False)


def _outside(values: pd.DataFrame, bounds: tuple[float, float]) -> pd.Series:
    lo, hi = bounds
    return ((values < lo) | (values > hi)).any(axis=1)


def _stuck_runs(context_y: pd.Series, y: pd.Series, min_hours: int) -> pd.Series:
    full = pd.concat([context_y.iloc[-(min_hours - 1):] if min_hours > 1 else context_y.iloc[0:0], y])
    grid = full.reindex(pd.date_range(full.index.min(), full.index.max(), freq=FREQ)) if len(full) else full
    run_id = (grid != grid.shift()).cumsum()
    run_len = grid.groupby(run_id).transform("size")
    stuck = (run_len >= min_hours) & grid.notna()
    return stuck.reindex(y.index, fill_value=False)


def _energy_rate_flags(context: pd.DataFrame, clean: pd.DataFrame, config: ValidationConfig) -> pd.DataFrame:
    """D6 (soft): energy used in an hour should roughly match the power readings.

    Power is an hourly snapshot and the chiller cycles within the hour, so this
    is loose and only logged (on 2024 data a ±20% rule would flag ~8% of rows).
    """
    both = pd.concat([context[[ENERGY, TARGET]].iloc[-1:], clean[[ENERGY, TARGET]]])
    consecutive = both.index.to_series().diff() == pd.Timedelta(hours=1)
    delta_e = both[ENERGY].diff()
    mean_p = (both[TARGET] + both[TARGET].shift()) / 2
    off = (delta_e - mean_p).abs() > config.energy_rate_rel_tolerance * mean_p + config.energy_rate_abs_tolerance_kwh
    hit = (consecutive & off & delta_e.notna()).reindex(clean.index, fill_value=False)
    detail = [f"energy delta {e:.1f} kWh vs mean power {p:.1f} kW" for e, p in zip(delta_e[hit.index][hit], mean_p[hit.index][hit])]
    return _flag_frame(hit[hit].index, "energy_rate_mismatch", detail)


def _spike_flags(context: pd.DataFrame, clean: pd.DataFrame, config: ValidationConfig) -> pd.DataFrame:
    """D8 (soft): far from the usual value for this hour of the week.

    Logged for review rather than quarantined: on 2024 data a hard rule would
    have removed ~6% of rows, nearly all genuine (compressor staging, breaks).
    """
    y = pd.concat([context[TARGET], clean[TARGET]]).dropna()
    how = y.index.dayofweek * 24 + y.index.hour
    grp = y.groupby(how)
    med = grp.transform("median")
    mad = (y - med).abs().groupby(how).transform("median") * 1.4826
    n = grp.transform("size")
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (y - med) / mad
    hit = ((z.abs() > config.spike_robust_z) & (mad > 0) & (n >= config.spike_min_samples)).reindex(clean.index, fill_value=False)
    detail = [f"robust z {v:.1f} for hour-of-week" for v in z.reindex(clean.index)[hit]]
    return _flag_frame(hit[hit].index, "spike", detail)


def _flag_frame(index: pd.Index, check: str, detail: list[str]) -> pd.DataFrame:
    return pd.DataFrame({INDEX_NAME: pd.DatetimeIndex(index), "check": check, "detail": detail})
