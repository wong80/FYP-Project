import numpy as np
import pandas as pd
import pytest

from chiller_forecast.gates import all_passed, evaluate, run_gates
from chiller_forecast.ingest import firebase_to_hourly
from chiller_forecast.settings import FirebaseConfig, GateConfig
from chiller_forecast.validation import READING_COLUMNS, validate

IDX = pd.date_range("2024-03-04", periods=24 * 14, freq="h")


def _truth():
    working = ((IDX.hour >= 9) & (IDX.hour <= 22)).astype(float)
    return pd.Series(50 + 300 * working, index=IDX)


def _metrics(noise: float, bias: float = 0.0, seed: int = 0):
    y = _truth()
    rng = np.random.default_rng(seed)
    pred = y.to_numpy() + bias + rng.normal(0, noise, len(y))
    naive = y + rng.normal(0, 40, len(y))  # "same hour last week" is decent but worse
    return evaluate(y, pred, naive)


def test_evaluate_basic_numbers():
    y = pd.Series([10.0, 20.0, 30.0, 40.0], index=pd.date_range("2024-03-04 08:00", periods=4, freq="h"))
    m = evaluate(y, np.array([12.0, 18.0, 30.0, 44.0]), pd.Series([np.nan, 10.0, 10.0, 10.0], index=y.index))
    assert m.mae == pytest.approx(2.0)
    assert m.bias == pytest.approx(-1.0)
    assert m.naive_mae == pytest.approx((10 + 20 + 30) / 3)  # NaN naive rows ignored
    assert m.segments["working_hours"] == pytest.approx((2 + 0 + 4) / 3)


def test_good_first_model_passes_without_champion():
    gates = run_gates(_metrics(5), None, historical_max=400, cfg=GateConfig())
    assert [g.name for g in gates] == ["G2_beats_naive", "G3_r2_floor", "G5_unbiased", "G6_plausible"]
    assert all_passed(gates)


def test_biased_model_fails_g5():
    gates = {g.name: g.passed for g in run_gates(_metrics(5, bias=25), None, 400, GateConfig())}
    assert not gates["G5_unbiased"]


def test_implausible_predictions_fail_g6():
    gates = {g.name: g.passed for g in run_gates(_metrics(5), None, historical_max=200, cfg=GateConfig())}
    assert not gates["G6_plausible"]


def test_must_clearly_beat_champion():
    champ = _metrics(5, seed=1)
    tie = run_gates(_metrics(5, seed=1), champ, 400, GateConfig())   # identical error: not 2% better
    better = run_gates(_metrics(2, seed=2), champ, 400, GateConfig())
    assert not {g.name: g.passed for g in tie}["G1_beats_champion"]
    assert all_passed(better)


def test_segment_regression_blocks_promotion():
    y = _truth()
    rng = np.random.default_rng(0)
    naive = y + rng.normal(0, 40, len(y))
    champ = evaluate(y, y.to_numpy() + rng.normal(0, 6, len(y)), naive)
    # Much better overall but clearly worse off-hours.
    pred = y.to_numpy().copy()
    off = (IDX.hour < 9) | (IDX.hour > 22)
    pred[off] += rng.choice([-10.0, 10.0], off.sum())
    chall = evaluate(y, pred, naive)
    gates = {g.name: g.passed for g in run_gates(chall, champ, 400, GateConfig())}
    assert gates["G1_beats_champion"] and not gates["G4_no_segment_regression"]


# --- Firebase ---------------------------------------------------------------

def _esp32_minutes(start="2024-03-04 09:00", minutes=150, watts=(30_000.0, 31_000.0, 29_000.0)):
    out = {}
    for i, ts in enumerate(pd.date_range(start, periods=minutes, freq="min")):
        rec = {"timestamp": f"{ts.day}/{ts.month}/{ts.year} {ts.hour}:{ts.minute}:{ts.second}"}  # RTC format, unpadded
        for n, w in enumerate(watts, start=1):
            rec[f"voltage{n}"] = "240.0"
            rec[f"current{n}"] = str(round(w / 240 / 0.9, 3))
            rec[f"power{n}"] = str(w)
        out[str(i)] = rec
    return out


def test_firebase_minutes_to_hours():
    now = pd.Timestamp("2024-03-04 11:40")
    hourly = firebase_to_hourly(_esp32_minutes(), FirebaseConfig(), now)
    # 09:00 and 10:00 complete; 11:00 is the current (still filling) hour.
    assert list(hourly.index) == [pd.Timestamp("2024-03-04 09:00"), pd.Timestamp("2024-03-04 10:00")]
    assert list(hourly.columns) == list(READING_COLUMNS)
    assert hourly["activePowerA"].iloc[0] == pytest.approx(30.0)  # W -> kW
    assert hourly["activePowerT"].iloc[0] == pytest.approx(90.0)
    assert hourly["importActiveEnergyT"].isna().all()
    assert len(validate(hourly, now=now).clean) == 2


def test_firebase_sparse_hour_dropped_and_bad_values_ignored():
    raw = _esp32_minutes(minutes=90)
    # Keep only 20 minutes of the second hour, and corrupt some fields.
    raw = {k: v for k, v in raw.items() if int(k) < 80}
    raw["0"]["power1"] = "nan"
    raw["1"]["timestamp"] = "garbage"
    hourly = firebase_to_hourly(raw, FirebaseConfig(), pd.Timestamp("2024-03-05"))
    assert list(hourly.index) == [pd.Timestamp("2024-03-04 09:00")]
    assert hourly["activePowerA"].iloc[0] == pytest.approx(30.0)


def test_firebase_list_payload_and_empty():
    as_list = list(_esp32_minutes(minutes=60).values())
    assert len(firebase_to_hourly([None, *as_list], FirebaseConfig(), pd.Timestamp("2024-03-05"))) == 1
    assert firebase_to_hourly(None, FirebaseConfig(), pd.Timestamp("2024-03-05")).empty
