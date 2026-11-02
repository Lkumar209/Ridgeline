"""Timestamp conventions for source data.

ComStock timeseries and its weather files share one convention, verified empirically in M1
(DECISIONS.md ADR-003):

* stamps are naive **local standard time** (UTC-5 all year, no daylight saving), and
* each stamp marks the **end** of its interval (the first 15-min row is 00:15).

Building schedules inside ComStock follow daylight saving, so after converting to
America/New_York an office's morning ramp lands on the same wall-clock hour in January and July.
Tariff demand windows are defined in wall-clock time, so this conversion is load-bearing.
"""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

# IANA "Etc/GMT+5" means UTC-5 (the sign is inverted by POSIX convention).
SOURCE_STANDARD_TZ = "Etc/GMT+5"


def standard_time_ending_to_utc_start(
    stamps: pd.DatetimeIndex | pd.Series, interval: timedelta
) -> pd.DatetimeIndex:
    """Convert naive local-standard, interval-ending stamps to UTC interval-start stamps."""
    index = pd.DatetimeIndex(stamps)
    if index.tz is not None:
        raise ValueError("expected naive timestamps in local standard time")
    return (index - interval).tz_localize(SOURCE_STANDARD_TZ).tz_convert("UTC")
