from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from ridgeline.assumptions import load_assumptions
from ridgeline.data.schemas import BatterySpec, LoadProfile, TouSchedule

START = datetime(2018, 1, 1, 5, tzinfo=UTC)


def test_load_profile_round_trips_through_series() -> None:
    profile = LoadProfile(site_id="s", interval_minutes=15, start=START, kw=[1.0, 2.0, 3.0])
    series = profile.to_series()
    assert str(pd.DatetimeIndex(series.index).tz) == "America/New_York"
    assert series.index[0].hour == 0  # 05:00 UTC is midnight EST
    assert LoadProfile.from_series("s", series) == profile


@pytest.mark.parametrize("kw", [[1.0, -0.1], [1.0, float("nan")], [float("inf")]])
def test_load_profile_rejects_bad_values(kw: list[float]) -> None:
    with pytest.raises(ValidationError):
        LoadProfile(site_id="s", interval_minutes=15, start=START, kw=kw)


def test_load_profile_rejects_naive_start() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        LoadProfile(site_id="s", interval_minutes=15, start=datetime(2018, 1, 1), kw=[1.0])


def test_from_series_rejects_irregular_index() -> None:
    index = pd.DatetimeIndex(["2018-01-01 00:00", "2018-01-01 00:15", "2018-01-01 00:45"], tz="UTC")
    with pytest.raises(ValueError, match="regularly spaced"):
        LoadProfile.from_series("s", pd.Series([1.0, 1.0, 1.0], index=index))


def test_tou_schedule_shape_and_period_checks() -> None:
    grid = [[0] * 24 for _ in range(12)]
    TouSchedule(rates=[0.1], weekday=grid, weekend=grid)
    with pytest.raises(ValidationError, match="12 x 24"):
        TouSchedule(rates=[0.1], weekday=grid[:11], weekend=grid)
    with pytest.raises(ValidationError, match="undefined period"):
        TouSchedule(rates=[0.1], weekday=[[1] * 24 for _ in range(12)], weekend=grid)


def test_battery_spec_from_assumptions_matches_brief_default() -> None:
    spec = BatterySpec.from_assumptions(load_assumptions())
    assert (spec.power_kw, spec.energy_kwh) == (125.0, 250.0)


def test_battery_spec_rejects_inverted_soc_bounds() -> None:
    with pytest.raises(ValidationError, match="soc_min"):
        BatterySpec(power_kw=1, energy_kwh=1, round_trip_efficiency=0.9, soc_min=0.9, soc_max=0.1)
