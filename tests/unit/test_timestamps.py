"""The ComStock timestamp convention: local standard time (UTC-5), interval-ending.

Demand-charge windows are wall-clock (America/New_York), so a one-hour error here would shift
every on-peak window for half the year. These tests pin both the pure conversion and the
empirical evidence from real ComStock data.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from ridgeline.data.comstock import LIGHTING_KWH_COL
from ridgeline.data.schemas import LOCAL_TZ
from ridgeline.data.timestamps import standard_time_ending_to_utc_start

Q = timedelta(minutes=15)


def _full_year_stamps() -> pd.DatetimeIndex:
    return pd.date_range("2018-01-01 00:15", "2019-01-01 00:00", freq="15min")


def test_first_stamp_becomes_midnight_est_interval_start() -> None:
    out = standard_time_ending_to_utc_start(pd.DatetimeIndex(["2018-01-01 00:15"]), Q)
    assert out[0] == pd.Timestamp("2018-01-01 05:00", tz="UTC")


def test_rejects_tz_aware_input() -> None:
    aware = pd.DatetimeIndex(["2018-01-01 00:15"]).tz_localize("UTC")
    with pytest.raises(ValueError, match="naive"):
        standard_time_ending_to_utc_start(aware, Q)


def test_summer_standard_stamp_is_one_hour_later_on_wall_clock() -> None:
    # Interval ending 12:00 EST covers 11:45-12:00 EST, which is 12:45-13:00 EDT.
    out = standard_time_ending_to_utc_start(pd.DatetimeIndex(["2018-07-02 12:00"]), Q)
    local = out.tz_convert(LOCAL_TZ)[0]
    assert (local.hour, local.minute) == (12, 45)


def test_full_year_has_dst_short_and_long_days_in_local_time() -> None:
    local = standard_time_ending_to_utc_start(_full_year_stamps(), Q).tz_convert(LOCAL_TZ)
    per_day = pd.Series(1, index=local).groupby(local.date).sum()
    assert len(local) == 35040
    assert per_day[pd.Timestamp("2018-03-11").date()] == 92  # spring forward: 23 hours
    assert per_day[pd.Timestamp("2018-11-04").date()] == 100  # fall back: 25 hours
    assert per_day[pd.Timestamp("2018-06-15").date()] == 96


def _weekday_profile(series: pd.Series) -> np.ndarray:
    weekdays = series[pd.DatetimeIndex(series.index).day_of_week < 5]
    index = pd.DatetimeIndex(weekdays.index)
    slot = index.hour * 4 + index.minute // 15
    profile = weekdays.groupby(slot).mean().reindex(range(96)).to_numpy()
    return np.asarray((profile - profile.mean()) / profile.std(), dtype=float)


def _schedule_shift_hours(winter: pd.Series, summer: pd.Series) -> float:
    """Hours by which the summer daily profile leads the winter one (circular x-corr)."""
    a, b = _weekday_profile(winter), _weekday_profile(summer)
    lags = range(-8, 9)
    scores = [float(np.dot(a, np.roll(b, lag))) for lag in lags]
    return lags[int(np.argmax(scores))] / 4


# The school in the fixture is excluded: its July profile is a summer-break schedule.
@pytest.mark.parametrize("bldg_id", [68361, 31197])
def test_lighting_schedule_is_same_wall_clock_time_in_winter_and_summer(
    raw_sample: pd.DataFrame, bldg_id: int
) -> None:
    """Regression test on real data: building schedules follow DST, timestamps do not.

    In raw standard-time stamps the July lighting schedule runs 1 h earlier than February's.
    After conversion to America/New_York both land on the same wall-clock time.
    """
    rows = raw_sample[raw_sample["bldg_id"] == bldg_id]
    raw_index = pd.DatetimeIndex(rows["timestamp"])
    lighting = rows[LIGHTING_KWH_COL].to_numpy()
    raw = pd.Series(lighting, index=raw_index - Q)
    local = pd.Series(
        lighting,
        index=standard_time_ending_to_utc_start(raw_index, Q).tz_convert(LOCAL_TZ),
    )

    def shift(s: pd.Series) -> float:
        month = pd.DatetimeIndex(s.index).month
        return _schedule_shift_hours(s[month == 2], s[month == 7])

    assert shift(raw) == 1.0
    assert shift(local) == 0.0
