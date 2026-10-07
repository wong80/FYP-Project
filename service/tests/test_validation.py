import numpy as np
import pandas as pd
import pytest

from chiller_forecast.settings import DEFAULT_GUARDRAILS, Guardrails
from chiller_forecast.validation import (
    BatchRejected,
    ValidationConfig,
    completeness,
    find_gaps,
    validate,
)

NOW = pd.Timestamp("2030-01-01")


def reasons(result) -> dict[pd.Timestamp, set[str]]:
    return {ts: set(r.split(";")) for ts, r in result.quarantine["reason"].items()}


def test_clean_data_passes(readings):
    r = validate(readings, now=NOW)
    assert len(r.clean) == len(readings)
    assert r.quarantine.empty and r.gaps.empty
    assert r.quarantine_rate == 0


def test_missing_column_rejects_batch(readings):
    with pytest.raises(BatchRejected):
        validate(readings.drop(columns=["voltageB"]), now=NOW)


def test_non_numeric_rejects_batch(readings):
    bad = readings.astype(object)
    bad.iloc[3, 2] = "n/a"
    with pytest.raises(BatchRejected):
        validate(bad, now=NOW)


def test_timezone_aware_index_rejected(readings):
    with pytest.raises(BatchRejected):
        validate(readings.tz_localize("UTC"), now=NOW)


def test_extra_columns_are_dropped(readings):
    r = validate(readings.assign(extra=1.0), now=NOW)
    assert "extra" not in r.clean.columns


def test_timestamp_checks(readings):
    df = readings.copy()
    future = pd.Timestamp("2024-03-10 12:00")
    df.index = df.index.where(df.index != readings.index[5], readings.index[5] + pd.Timedelta(minutes=17))
    r = validate(df, now=future)
    got = reasons(r)
    assert "not_hour_aligned" in got[readings.index[5] + pd.Timedelta(minutes=17)]
    assert all("future_timestamp" in v for ts, v in got.items() if ts > future + pd.Timedelta(minutes=5))
    assert (r.clean.index <= future).all()


def test_exact_duplicate_collapses_conflicting_duplicate_quarantined(readings):
    exact = readings.iloc[[10]]
    conflicting = readings.iloc[[20]].assign(activePowerT=lambda d: d.activePowerT + 1)
    r = validate(pd.concat([readings, exact, conflicting]), now=NOW)
    assert readings.index[10] in r.clean.index
    assert readings.index[20] not in r.clean.index
    assert (r.quarantine.loc[readings.index[20], "reason"] == "conflicting_duplicate").all()
    assert len(r.quarantine.loc[[readings.index[20]]]) == 2


@pytest.mark.parametrize("col, value, reason", [
    ("voltageA", 150.0, "phase_voltage_out_of_range"),
    ("voltageL12", 600.0, "line_voltage_out_of_range"),
    ("currentB", -1.0, "current_out_of_range"),
    ("currentC", 5000.0, "current_out_of_range"),
    ("voltageC", np.nan, "missing_value"),
])
def test_range_and_missing_checks(readings, col, value, reason):
    df = readings.copy()
    t = df.index[30]
    df.loc[t, col] = value
    assert reason in reasons(validate(df, now=NOW))[t]


def test_total_power_out_of_range(readings):
    df = readings.copy()
    t = df.index[30]
    df.loc[t, ["activePowerT", "activePowerA", "activePowerB", "activePowerC"]] = [1500, 500, 500, 500]
    assert "power_out_of_range" in reasons(validate(df, now=NOW))[t]


def test_optional_columns_may_be_missing(readings):
    """The ESP32 has no energy counter or line voltages."""
    df = readings.assign(importActiveEnergyT=np.nan, voltageL12=np.nan, voltageL23=np.nan, voltageL31=np.nan)
    r = validate(df, now=NOW)
    assert len(r.clean) == len(df)


def test_phase_sum_identity(readings):
    df = readings.copy()
    t = df.index[40]
    df.loc[t, "activePowerT"] += 3.0
    assert reasons(validate(df, now=NOW))[t] == {"phase_sum_mismatch"}


def test_power_cannot_exceed_apparent(readings):
    df = readings.copy()
    t = df.index[50]
    df.loc[t, "currentA"] = df.loc[t, "activePowerA"] * 1000 / df.loc[t, "voltageA"] * 0.5
    assert reasons(validate(df, now=NOW))[t] == {"power_exceeds_apparent"}


def test_energy_counter_decrease_uses_context(readings):
    ctx, batch = readings.iloc[:100], readings.iloc[100:].copy()
    batch.iloc[0, batch.columns.get_loc("importActiveEnergyT")] = ctx["importActiveEnergyT"].iloc[-1] - 10
    r = validate(batch, context=ctx, now=NOW)
    assert reasons(r)[batch.index[0]] == {"energy_counter_decreased"}
    assert batch.index[0] not in r.clean.index
    # context rows are reference only, never returned
    assert r.clean.index.min() >= batch.index[0]


def test_stuck_sensor_run_including_context(readings):
    df = readings.copy()
    df.iloc[98:104, df.columns.get_loc("activePowerT")] = 123.456  # 6 identical hours
    ctx, batch = df.iloc[:100], df.iloc[100:]
    r = validate(batch, context=ctx, now=NOW)
    stuck = [ts for ts, v in reasons(r).items() if "stuck_sensor" in v]
    assert stuck == list(df.index[100:104])


def test_five_equal_hours_is_not_stuck(readings):
    df = readings.copy()
    df.iloc[10:15, df.columns.get_loc("activePowerT")] = 123.456
    df.iloc[10:15, df.columns.get_loc("activePowerA")] += 123.456 - df["activePowerT"].iloc[10:15]  # keep identity
    assert not any("stuck_sensor" in v for v in reasons(validate(df, now=NOW)).values())


def test_gaps_are_reported_not_filled(readings):
    holed = readings.drop(readings.index[50:53])
    r = validate(holed, now=NOW)
    assert len(r.clean) == len(holed)
    assert r.gaps.to_dict("records") == [{"gap_start": readings.index[50], "gap_end": readings.index[52], "missing_hours": 3}]


def test_gap_between_context_and_batch():
    from .conftest import make_readings

    df = make_readings(hours=48)
    gaps = find_gaps(df.iloc[:10], df.iloc[15:])
    assert gaps["missing_hours"].tolist() == [5]


def test_soft_flags_do_not_quarantine(readings):
    df = readings.copy()
    t = df.index[24 * 14 + 12]  # enough same-hour-of-week history
    for col in ("activePowerA", "activePowerB", "activePowerC"):
        df.loc[t, col] *= 2.5
    df.loc[t, "activePowerT"] = df.loc[t, ["activePowerA", "activePowerB", "activePowerC"]].sum()
    for p in "ABC":
        df.loc[t, f"current{p}"] *= 2.5
    r = validate(df, now=NOW, config=ValidationConfig(spike_min_samples=2))
    assert t in r.clean.index
    assert "spike" in set(r.flags.loc[r.flags["dateTime"] == t, "check"])


def test_completeness():
    idx = pd.date_range("2024-01-01", periods=90, freq="h")
    assert completeness(idx, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-01") + pd.Timedelta(hours=100)) == pytest.approx(0.9)
    assert completeness(idx, pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-01")) == 0.0


def test_real_dataset_quarantines_only_physically_inconsistent_rows(real_data):
    r = validate(real_data, now=NOW)
    counts = r.quarantine["reason"].value_counts().to_dict()
    assert counts == {"phase_sum_mismatch": 7, "power_exceeds_apparent": 6}
    assert r.quarantine_rate < 0.005
    assert r.gaps["missing_hours"].sum() == 3 + 13  # the dataset's own 3-hour gap + the 13 quarantined hours


def test_incremental_batch_matches_full_run(real_data):
    """Validating hour by hour with context gives the same answer as all at once."""
    full = validate(real_data, now=NOW)
    ctx, batch = real_data.iloc[:-72], real_data.iloc[-72:]
    inc = validate(batch, context=ctx, now=NOW)
    pd.testing.assert_frame_equal(inc.clean, full.clean.loc[batch.index.min():])


def test_config_file_loads_and_matches_defaults():
    g = Guardrails.load(DEFAULT_GUARDRAILS)
    assert g.validation == ValidationConfig()


def test_unknown_config_key_rejected():
    with pytest.raises(ValueError):
        ValidationConfig.from_dict({"phase_volts": [1, 2]})
