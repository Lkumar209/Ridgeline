"""Property tests for the load-profile and timestamp plumbing that every later stage uses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
from hypothesis import given
from hypothesis import strategies as st

from ridgeline.data.schemas import LoadProfile
from ridgeline.data.timestamps import standard_time_ending_to_utc_start

kw_values = st.lists(
    st.floats(min_value=0, max_value=5_000, allow_nan=False), min_size=2, max_size=300
)
starts = st.datetimes(min_value=datetime(2018, 1, 1), max_value=datetime(2018, 12, 30)).map(
    lambda d: d.replace(second=0, microsecond=0, minute=(d.minute // 15) * 15, tzinfo=UTC)
)


@given(kw=kw_values, start=starts)
def test_profile_series_round_trip_preserves_values_and_instants(
    kw: list[float], start: datetime
) -> None:
    profile = LoadProfile(site_id="s", interval_minutes=15, start=start, kw=kw)
    series = profile.to_series()
    assert len(series) == len(kw)
    assert series.index[0] == pd.Timestamp(start)
    assert LoadProfile.from_series("s", series) == profile


@given(n=st.integers(min_value=1, max_value=2_000), minutes=st.sampled_from([15, 60]))
def test_conversion_preserves_count_and_uniform_spacing(n: int, minutes: int) -> None:
    step = timedelta(minutes=minutes)
    stamps = pd.date_range("2018-03-10 00:00", periods=n, freq=f"{minutes}min") + step
    out = standard_time_ending_to_utc_start(stamps, step)
    assert len(out) == n
    if n > 1:
        assert ((out[1:] - out[:-1]) == step).all()
    assert out[0] == pd.Timestamp("2018-03-10 05:00", tz="UTC")
