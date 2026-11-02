"""County weather (ComStock AMY2018 CSVs): hourly, local standard time, hour-ending."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

from ridgeline.data.timestamps import standard_time_ending_to_utc_start

COLUMNS = {
    "Dry Bulb Temperature [°C]": "temp_c",
    "Relative Humidity [%]": "rh_pct",
    "Wind Speed [m/s]": "wind_ms",
    "Global Horizontal Radiation [W/m2]": "ghi_wm2",
}


def normalize_weather(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw weather CSV frame -> selected columns indexed by UTC hour start."""
    stamps = pd.to_datetime(raw["date_time"])
    index = standard_time_ending_to_utc_start(stamps, timedelta(hours=1))
    df = raw[list(COLUMNS)].rename(columns=COLUMNS)
    df.index = index
    return df


def load_weather(path: Path) -> pd.DataFrame:
    return normalize_weather(pd.read_csv(path))
