"""Simulate utility-meter outages by masking stretches of a load series.

A gap is a half-open interval [start, end) in UTC. Gaps are drawn with a seeded generator so
experiments are reproducible.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator


class Gap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _ordered_and_aware(self) -> Gap:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("gap bounds must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("gap end must be after start")
        return self

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


def sample_gaps(
    index: pd.DatetimeIndex,
    n: int,
    min_days: int,
    max_days: int,
    rng: np.random.Generator,
) -> list[Gap]:
    """Draw `n` gaps of whole-day length in [min_days, max_days] that fit inside `index`.

    Start positions are uniform over valid intervals, so gaps can begin at any time of day.
    """
    step = index[1] - index[0]
    per_day = int(timedelta(days=1) / step)
    gaps = []
    for _ in range(n):
        n_intervals = int(rng.integers(min_days, max_days + 1)) * per_day
        if n_intervals >= len(index):
            raise ValueError("gap longer than the series")
        pos = int(rng.integers(0, len(index) - n_intervals + 1))
        start = index[pos]
        gaps.append(
            Gap(start=start.to_pydatetime(), end=(start + n_intervals * step).to_pydatetime())
        )
    return gaps


def gap_mask(index: pd.DatetimeIndex, gap: Gap) -> np.ndarray:
    """Boolean array, True for intervals inside the gap."""
    start, end = pd.Timestamp(gap.start), pd.Timestamp(gap.end)
    return np.asarray((index >= start) & (index < end), dtype=bool)


def apply_gap(series: pd.Series, gap: Gap) -> pd.Series:
    """Copy of `series` with the gap's intervals set to NaN."""
    out = series.copy()
    out[gap_mask(pd.DatetimeIndex(series.index), gap)] = np.nan
    return out


def missing_runs(series: pd.Series) -> list[tuple[int, int]]:
    """Positions [start, end) of each contiguous run of NaN values."""
    missing = series.isna().to_numpy()
    if not missing.any():
        return []
    padded = np.concatenate([[False], missing, [False]])
    edges = np.flatnonzero(np.diff(padded.astype(np.int8)))
    return [(int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True)]
