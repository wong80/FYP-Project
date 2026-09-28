"""Holdout metrics and promotion gates G1-G6 (DESIGN.md §4.3).

G7 (wins across several weekly windows) and G8 (shadow period) need a history
of live forecasts and are added in phase 3.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .settings import GateConfig

SEGMENTS = {
    "working_hours": lambda idx: (idx.hour >= 9) & (idx.hour <= 22),
    "off_hours": lambda idx: (idx.hour < 9) | (idx.hour > 22),
    "weekday": lambda idx: idx.dayofweek < 5,
    "weekend": lambda idx: idx.dayofweek >= 5,
}


@dataclass
class Metrics:
    n: int
    mae: float
    rmse: float
    r2: float
    bias: float
    naive_mae: float
    min_pred: float
    max_pred: float
    segments: dict[str, float]

    def flat(self, prefix: str = "") -> dict[str, float]:
        out = {f"{prefix}{k}": v for k, v in asdict(self).items() if k != "segments"}
        out.update({f"{prefix}mae_{k}": v for k, v in self.segments.items()})
        return out


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


def evaluate(y_true: pd.Series, y_pred: np.ndarray, naive: pd.Series) -> Metrics:
    """Error metrics on the holdout. ``naive`` is the seasonal-naive forecast (same hour last week)."""
    y = y_true.to_numpy(dtype=float)
    p = np.asarray(y_pred, dtype=float)
    err = y - p
    ss_tot = float(((y - y.mean()) ** 2).sum())
    has_naive = naive.notna().to_numpy()
    idx = y_true.index
    segments = {}
    for name, rule in SEGMENTS.items():
        mask = np.asarray(rule(idx))
        segments[name] = float(np.abs(err[mask]).mean()) if mask.any() else float("nan")
    return Metrics(
        n=len(y),
        mae=float(np.abs(err).mean()),
        rmse=float(np.sqrt((err ** 2).mean())),
        r2=1 - float((err ** 2).sum()) / ss_tot if ss_tot > 0 else float("nan"),
        bias=float(err.mean()),
        naive_mae=float(np.abs(y[has_naive] - naive.to_numpy(dtype=float)[has_naive]).mean()) if has_naive.any() else float("nan"),
        min_pred=float(p.min()),
        max_pred=float(p.max()),
        segments=segments,
    )


def run_gates(challenger: Metrics, champion: Metrics | None, historical_max: float, cfg: GateConfig) -> list[GateResult]:
    gates = [
        GateResult("G2_beats_naive", challenger.mae <= cfg.max_vs_naive * challenger.naive_mae,
                   f"MAE {challenger.mae:.2f} vs {cfg.max_vs_naive} x naive {challenger.naive_mae:.2f}"),
        GateResult("G3_r2_floor", challenger.r2 >= cfg.min_r2, f"R2 {challenger.r2:.3f} >= {cfg.min_r2}"),
        GateResult("G5_unbiased", abs(challenger.bias) <= cfg.max_abs_bias_kw,
                   f"|bias| {abs(challenger.bias):.2f} kW <= {cfg.max_abs_bias_kw}"),
        GateResult("G6_plausible", challenger.min_pred >= 0 and challenger.max_pred <= cfg.max_pred_vs_hist_max * historical_max,
                   f"predictions in [{challenger.min_pred:.1f}, {challenger.max_pred:.1f}] kW, limit {cfg.max_pred_vs_hist_max * historical_max:.1f}"),
    ]
    if champion is not None:
        gates.insert(0, GateResult(
            "G1_beats_champion", challenger.mae <= champion.mae * (1 - cfg.min_improvement),
            f"MAE {challenger.mae:.2f} vs champion {champion.mae:.2f} (needs {cfg.min_improvement:.0%} better)",
        ))
        worse = {k: v for k, v in challenger.segments.items()
                 if not np.isnan(v) and not np.isnan(champion.segments.get(k, np.nan))
                 and v > cfg.max_segment_regression * champion.segments[k]}
        gates.insert(1, GateResult("G4_no_segment_regression", not worse,
                                   "ok" if not worse else f"worse on {sorted(worse)}"))
    return gates


def all_passed(gates: list[GateResult]) -> bool:
    return all(g.passed for g in gates)
