"""Calendar and weather features shared by the imputers.

Calendar features use local wall-clock time (America/New_York), because building schedules
follow daylight saving (DECISIONS.md ADR-003).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ridgeline.data.schemas import LOCAL_TZ

SLOTS_PER_DAY = 96


def _local(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index.tz_convert(LOCAL_TZ)


def is_weekend(index: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(_local(index).day_of_week >= 5, dtype=bool)


def slot_of_day(index: pd.DatetimeIndex) -> np.ndarray:
    """15-minute slot of the local day, 0..95."""
    local = _local(index)
    return np.asarray(local.hour * 4 + local.minute // 15, dtype=np.int64)


def local_hour(index: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(_local(index).hour, dtype=np.int64)


def slot_daytype_dummies(index: pd.DatetimeIndex) -> np.ndarray:
    """One-hot (weekday/weekend x local 15-min slot): 192 columns, exactly one 1 per row.

    Matches the data's 15-min resolution; hourly dummies flatten intra-hour peaks.
    """
    col = slot_of_day(index) + SLOTS_PER_DAY * is_weekend(index).astype(np.int64)
    out = np.zeros((len(index), 2 * SLOTS_PER_DAY))
    out[np.arange(len(index)), col] = 1.0
    return out


def temperature_on_index(weather: pd.DataFrame, index: pd.DatetimeIndex) -> np.ndarray:
    """Hourly dry-bulb temperature carried forward onto a finer interval index.

    `weather` is indexed by UTC hour start (see `data/weather.py`), so each 15-min interval
    takes the temperature of the hour it falls in.
    """
    temp = weather["temp_c"].reindex(index, method="ffill")
    if temp.isna().any():
        raise ValueError("weather does not cover the load index")
    return temp.to_numpy(dtype=float)


def degree_features(
    temp_c: np.ndarray,
    occupied: np.ndarray,
    cooling_base_c: float,
    heating_base_c: float,
) -> np.ndarray:
    """Cooling and heating degree terms, plain and interacted with occupancy: 4 columns."""
    cooling = np.maximum(temp_c - cooling_base_c, 0.0)
    heating = np.maximum(heating_base_c - temp_c, 0.0)
    occ = occupied.astype(float)
    return np.column_stack([cooling, heating, cooling * occ, heating * occ])


def occupied_hours(index: pd.DatetimeIndex) -> np.ndarray:
    """Crude occupancy proxy: weekdays 07:00-19:00 local. A modeling choice, not a fact."""
    hour = local_hour(index)
    return ~is_weekend(index) & (hour >= 7) & (hour < 19)


def peer_signal(peers: list[pd.Series], index: pd.DatetimeIndex) -> np.ndarray:
    """Mean of peers' loads, each normalized by its own annual mean (~1.0 on average).

    Peers are other sites of the same building type. They must have data at every interval.
    """
    if not peers:
        raise ValueError("peer_signal needs at least one peer")
    normalized = [p.reindex(index) / p.mean() for p in peers]
    stacked = np.column_stack([s.to_numpy(dtype=float) for s in normalized])
    if np.isnan(stacked).any():
        raise ValueError("peer series do not cover the load index")
    return np.asarray(stacked.mean(axis=1), dtype=float)
