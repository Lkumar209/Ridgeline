"""Baseline imputer: fill a gap with the site's own recent typical-day profile."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd

from ridgeline.gaps.features import is_weekend, slot_of_day
from ridgeline.gaps.inject import missing_runs


def seasonal_profile_fill(series: pd.Series, window_days: int) -> pd.Series:
    """Fill each NaN run with the mean (weekday/weekend, 15-min slot) profile of the
    observed data within `window_days` before and after the run.

    Simple and explainable. Its known weakness: a long summer gap is filled from spring and
    autumn days, so it misses weather-driven peaks.
    """
    out = series.copy()
    index = pd.DatetimeIndex(series.index)
    window = timedelta(days=window_days)
    for a, b in missing_runs(series):
        start, end = index[a], index[b - 1] + (index[1] - index[0])
        near = ((index >= start - window) & (index < start)) | (
            (index >= end) & (index < end + window)
        )
        ref = series[near].dropna()
        if ref.empty:
            raise ValueError(f"no observed data within {window_days} days of the gap")
        out.iloc[a:b] = _profile_values(ref, index[a:b])
    return out


def _profile_values(ref: pd.Series, target: pd.DatetimeIndex) -> np.ndarray:
    ref_index = pd.DatetimeIndex(ref.index)
    keys = pd.MultiIndex.from_arrays([is_weekend(ref_index), slot_of_day(ref_index)])
    profile = pd.Series(ref.to_numpy(), index=keys).groupby(level=[0, 1]).mean()
    slot_only = pd.Series(ref.to_numpy(), index=slot_of_day(ref_index)).groupby(level=0).mean()

    target_keys = pd.MultiIndex.from_arrays([is_weekend(target), slot_of_day(target)])
    values = profile.reindex(target_keys).to_numpy(dtype=float)
    # If the window lacks a day type (e.g. no weekend observed), fall back to the slot mean.
    fallback = slot_only.reindex(slot_of_day(target)).to_numpy(dtype=float)
    return np.where(np.isnan(values), fallback, values)
