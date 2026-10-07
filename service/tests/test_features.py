import numpy as np
import pandas as pd
import pytest

from chiller_forecast.features import (
    FEATURES,
    MAX_LOOKBACK_H,
    NOTEBOOK_FEATURES,
    RECENT_LAGS,
    TARGET,
    build_features,
    features_for_hour,
    trainable_rows,
)

from .conftest import make_readings


def notebook_features(df: pd.DataFrame) -> pd.DataFrame:
    """Verbatim copy of create_enhanced_features from MLJAR_AutoML_Improved.ipynb (reference)."""
    df = df.copy()
    df["hour"] = df.index.hour
    df["dayofweek"] = df.index.dayofweek
    df["quarter"] = df.index.quarter
    df["month"] = df.index.month
    df["dayofyear"] = df.index.dayofyear
    df["dayofmonth"] = df.index.day
    df["weekofyear"] = df.index.isocalendar().week.astype(int)
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["dow_sin"] = np.sin(2 * np.pi * df["dayofweek"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["dayofweek"] / 7)
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    df["is_weekend"] = (df["dayofweek"] >= 5).astype(int)
    df["is_working_hours"] = ((df["hour"] >= 9) & (df["hour"] <= 22)).astype(int)
    target_map = df["activePowerT"].to_dict()
    df["lag_24h"] = (df.index - pd.Timedelta("24 hours")).map(target_map)
    df["lag_7d"] = (df.index - pd.Timedelta("7 days")).map(target_map)
    df["lag_8d"] = (df.index - pd.Timedelta("8 days")).map(target_map)
    df["lag_9d"] = (df.index - pd.Timedelta("9 days")).map(target_map)
    df["lag_10d"] = (df.index - pd.Timedelta("10 days")).map(target_map)
    df["lag_14d"] = (df.index - pd.Timedelta("14 days")).map(target_map)
    powerA_map = df["activePowerA"].to_dict()
    currentA_map = df["currentA"].to_dict()
    df["activePowerA_lag1"] = (df.index - pd.Timedelta("7 days")).map(powerA_map)
    df["currentA_lag1"] = (df.index - pd.Timedelta("7 days")).map(currentA_map)
    df["activePowerA_lag2"] = (df.index - pd.Timedelta("14 days")).map(powerA_map)
    df["currentA_lag2"] = (df.index - pd.Timedelta("14 days")).map(currentA_map)
    df["rolling_mean_24h"] = df["activePowerT"].shift(1).rolling(window=24, min_periods=1).mean()
    df["rolling_std_24h"] = df["activePowerT"].shift(1).rolling(window=24, min_periods=1).std()
    df["rolling_mean_7d"] = df["activePowerT"].shift(1).rolling(window=168, min_periods=1).mean()
    df["rolling_std_7d"] = df["activePowerT"].shift(1).rolling(window=168, min_periods=1).std()
    df["diff_24h"] = df["lag_24h"] - df["lag_7d"]
    return df


def test_matches_notebook_on_gapless_data(readings):
    ours = build_features(readings)[NOTEBOOK_FEATURES]
    ref = notebook_features(readings)[NOTEBOOK_FEATURES]
    pd.testing.assert_frame_equal(ours, ref, check_dtype=False)


def test_matches_notebook_on_real_data_where_no_gap_is_involved(real_data):
    ours = build_features(real_data).reindex(real_data.index)[NOTEBOOK_FEATURES]
    ref = notebook_features(real_data)[NOTEBOOK_FEATURES]
    # The notebook's row-based windows bridge the dataset's 4-hour gap; compare
    # only rows whose look-back window doesn't reach a gap.
    step = real_data.index.to_series().diff()
    last_gap = step[step > pd.Timedelta(hours=1)].index.max()
    safe = real_data.index >= last_gap + pd.Timedelta(hours=MAX_LOOKBACK_H)
    assert safe.sum() > 1000
    pd.testing.assert_frame_equal(ours[safe], ref[safe], check_dtype=False)


def test_feature_list_is_notebook_list_plus_recent_lags():
    assert len(NOTEBOOK_FEATURES) == 30
    assert FEATURES == NOTEBOOK_FEATURES + RECENT_LAGS
    assert len(set(FEATURES)) == len(FEATURES)


def test_recent_lags(readings):
    feats = build_features(readings)
    t = readings.index[100]
    for n in (1, 2, 3):
        assert feats.loc[t, f"lag_{n}h"] == readings.loc[t - pd.Timedelta(hours=n), TARGET]


@pytest.mark.parametrize("pos", [MAX_LOOKBACK_H + 5, MAX_LOOKBACK_H + 100])
def test_no_look_ahead(readings, pos):
    """T3: changing the reading at t (or later) must not change any feature at t."""
    t = readings.index[pos]
    base = build_features(readings).loc[t, FEATURES]
    changed = readings.copy()
    changed.loc[changed.index >= t, ["activePowerT", "activePowerA", "currentA"]] *= 7.0
    after = build_features(changed).loc[t, FEATURES]
    pd.testing.assert_series_equal(base, after)


def test_gap_is_not_bridged(readings):
    """A lag is 'n real hours ago', even when rows are missing in between."""
    holed = readings.drop(readings.index[400:404])
    feats = build_features(holed)
    assert len(feats) == len(readings)                 # missing hours restored as rows...
    assert feats.loc[readings.index[400:404], TARGET].isna().all()  # ...with no invented target
    t = readings.index[450]
    assert feats.loc[t, "lag_24h"] == readings.loc[t - pd.Timedelta(hours=24), TARGET]
    # 24 h rolling window ending at t-1 covers the 4 missing hours: mean of the 20 present.
    window = holed.loc[(holed.index >= t - pd.Timedelta(hours=24)) & (holed.index < t), TARGET]
    t_in = readings.index[410]
    window_in = holed.loc[(holed.index >= t_in - pd.Timedelta(hours=24)) & (holed.index < t_in), TARGET]
    assert len(window_in) == 20
    assert feats.loc[t_in, "rolling_mean_24h"] == pytest.approx(window_in.mean())
    assert feats.loc[t, "rolling_mean_24h"] == pytest.approx(window.mean())


def test_trainable_rows_drops_missing_targets(readings):
    feats = build_features(readings.drop(readings.index[10:13]))
    assert trainable_rows(feats)[TARGET].notna().all()
    assert len(trainable_rows(feats)) == len(readings) - 3


def test_features_for_hour_equals_training_features(readings):
    """T2: the scorer's single-row path gives exactly the training features."""
    full = build_features(readings)
    for t in readings.index[[MAX_LOOKBACK_H + 1, -1]]:
        row = features_for_hour(readings[readings.index < t], t)
        pd.testing.assert_series_equal(row.iloc[0], full.loc[t, FEATURES], check_names=False)


def test_features_for_next_hour(readings):
    nxt = readings.index[-1] + pd.Timedelta(hours=1)
    row = features_for_hour(readings, nxt)
    assert list(row.columns) == FEATURES and row.index[0] == nxt
    assert row.iloc[0]["lag_24h"] == readings.loc[nxt - pd.Timedelta(hours=24), TARGET]


def test_features_for_hour_rejects_bad_input(readings):
    with pytest.raises(ValueError):
        features_for_hour(readings, readings.index[-1] + pd.Timedelta(minutes=30))
    with pytest.raises(ValueError):
        features_for_hour(readings, readings.index[0])


@pytest.mark.parametrize("mutate, error", [
    (lambda d: d.iloc[::-1], ValueError),
    (lambda d: pd.concat([d, d.iloc[:1]]), ValueError),
    (lambda d: d.set_axis(d.index + pd.Timedelta(minutes=20)), ValueError),
    (lambda d: d.reset_index(drop=True), TypeError),
    (lambda d: d.drop(columns=["currentA"]), KeyError),
])
def test_rejects_malformed_frames(readings, mutate, error):
    with pytest.raises(error):
        build_features(mutate(readings))


def test_make_readings_is_deterministic():
    pd.testing.assert_frame_equal(make_readings(seed=3), make_readings(seed=3))
