from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chiller_forecast.validation import INDEX_NAME, READING_COLUMNS

DATASET = Path(__file__).resolve().parents[2] / "Datasets" / "Combined.xlsx"


def make_readings(hours: int = 24 * 21, start: str = "2024-03-04 00:00", seed: int = 0) -> pd.DataFrame:
    """Physically consistent synthetic hourly readings (passes every hard check)."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=hours, freq="h", name=INDEX_NAME)
    working = ((idx.hour >= 9) & (idx.hour <= 22)).astype(float)
    base = 20 + 300 * working * np.where(idx.dayofweek >= 5, 0.5, 1.0)
    total = base + rng.normal(0, 15, hours).clip(-15, 15)
    share = np.array([0.3, 0.37, 0.33])
    df = pd.DataFrame(index=idx)
    for phase, s in zip("ABC", share):
        p = total * s
        df[f"voltage{phase}"] = 240 + rng.normal(0, 3, hours)
        df[f"activePower{phase}"] = p
        df[f"current{phase}"] = p * 1000 / df[f"voltage{phase}"] / 0.9  # PF 0.9
    df["activePowerT"] = df[["activePowerA", "activePowerB", "activePowerC"]].sum(axis=1)
    df["importActiveEnergyT"] = 2_600_000 + df["activePowerT"].cumsum()
    for col in ("voltageL12", "voltageL23", "voltageL31"):
        df[col] = 415 + rng.normal(0, 3, hours)
    return df[list(READING_COLUMNS)]


@pytest.fixture
def readings() -> pd.DataFrame:
    return make_readings()


@pytest.fixture(scope="session")
def real_data() -> pd.DataFrame:
    if not DATASET.exists():
        pytest.skip("Datasets/Combined.xlsx not available")
    return pd.read_excel(DATASET).set_index(INDEX_NAME).sort_index()
