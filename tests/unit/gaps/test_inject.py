from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from ridgeline.gaps.inject import Gap, apply_gap, gap_mask, missing_runs, sample_gaps
from tests.gaps_helpers import weekly_profile_series, year_index


def test_sampled_gaps_fit_and_have_whole_day_lengths() -> None:
    index = year_index()
    gaps = sample_gaps(index, n=50, min_days=30, max_days=92, rng=np.random.default_rng(1))
    for gap in gaps:
        assert 30 <= gap.duration.days <= 92
        assert gap.duration == timedelta(days=gap.duration.days)
        assert gap.start >= index[0] and gap.end <= index[-1] + timedelta(minutes=15)


def test_sampling_is_reproducible() -> None:
    index = year_index()
    a = sample_gaps(index, 5, 30, 92, np.random.default_rng(3))
    b = sample_gaps(index, 5, 30, 92, np.random.default_rng(3))
    assert a == b


def test_gap_longer_than_series_is_rejected() -> None:
    index = year_index()[: 96 * 10]
    with pytest.raises(ValueError, match="longer than the series"):
        sample_gaps(index, 1, 30, 30, np.random.default_rng(0))


def test_apply_gap_masks_exactly_the_gap_and_copies() -> None:
    series = weekly_profile_series(year_index())
    start = datetime(2018, 3, 1, 5, tzinfo=UTC)
    gap = Gap(start=start, end=start + timedelta(days=31))
    masked = apply_gap(series, gap)
    assert int(masked.isna().sum()) == 31 * 96
    assert not series.isna().any()  # input untouched
    assert gap_mask(pd.DatetimeIndex(series.index), gap).sum() == 31 * 96


def test_gap_validation() -> None:
    start = datetime(2018, 3, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="after start"):
        Gap(start=start, end=start)
    with pytest.raises(ValidationError, match="timezone-aware"):
        Gap(start=datetime(2018, 3, 1), end=datetime(2018, 3, 2))


def test_missing_runs_finds_each_run() -> None:
    s = pd.Series([1.0, np.nan, np.nan, 2.0, np.nan, 3.0, np.nan])
    assert missing_runs(s) == [(1, 3), (4, 5), (6, 7)]
    assert missing_runs(pd.Series([1.0, 2.0])) == []
