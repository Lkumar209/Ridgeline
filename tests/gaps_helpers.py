"""Synthetic year-long series with known structure, for imputer tests."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ridgeline.gaps.features import is_weekend, slot_of_day


def year_index(freq: str = "15min") -> pd.DatetimeIndex:
    """2018 in UTC interval-start stamps, matching normalized ComStock data."""
    return pd.date_range("2018-01-01 05:00", "2019-01-01 04:45", freq=freq, tz="UTC")


def weekly_profile_series(index: pd.DatetimeIndex) -> pd.Series:
    """Perfectly repeating weekday/weekend daily shape, no weather dependence."""
    slot = slot_of_day(index)
    weekday_shape = 50 + 40 * np.sin(np.pi * slot / 96) ** 2
    values = np.where(is_weekend(index), 30.0, weekday_shape)
    return pd.Series(values, index=index, name="kw")


def synthetic_weather(seed: int = 0) -> pd.DataFrame:
    """Hourly temperature: seasonal cycle plus a daily swing plus noise."""
    index = year_index("1h")
    day = np.arange(len(index)) / 24
    rng = np.random.default_rng(seed)
    temp = 10 - 14 * np.cos(2 * np.pi * day / 365) + 4 * np.sin(2 * np.pi * (day % 1) - 2)
    return pd.DataFrame({"temp_c": temp + rng.normal(0, 1, len(index))}, index=index)
