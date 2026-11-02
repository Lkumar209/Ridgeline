"""Shared builders for battery and billing tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ridgeline.data.schemas import BatterySpec, Tariff
from ridgeline.data.tariffs import parse_urdb_record

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tariff_test_fixture.json"
SPEC = BatterySpec(
    power_kw=125, energy_kwh=250, round_trip_efficiency=0.88, soc_min=0.05, soc_max=0.95
)


def fixture_tariff() -> Tariff:
    record = json.loads(FIXTURE.read_text())["items"][0]
    return parse_urdb_record(record, "fixture")


def flat_demand_tariff(rate: float = 10.0, energy: float = 0.10) -> Tariff:
    """Single energy price, flat monthly demand charge only: built from the fake fixture."""
    record = json.loads(FIXTURE.read_text())["items"][0]
    zeros = [[0] * 24 for _ in range(12)]
    record.update(
        energyratestructure=[[{"rate": energy}]],
        energyweekdayschedule=zeros,
        energyweekendschedule=zeros,
        flatdemandstructure=[[{"rate": rate}]],
        flatdemandmonths=[0] * 12,
    )
    for key in ("demandratestructure", "demandweekdayschedule", "demandweekendschedule"):
        record.pop(key)
    return parse_urdb_record(record, "flat")


def office_like_load(days: int, start: str = "2018-01-01 05:00", seed: int = 0) -> pd.Series:
    """Weekday afternoon peaks over a base load, with noise. UTC interval-start index."""
    index = pd.date_range(start, periods=days * 96, freq="15min", tz="UTC")
    local = index.tz_convert("America/New_York")
    hour = np.asarray(local.hour + local.minute / 60)
    weekday = np.asarray(local.day_of_week < 5)
    shape = 80 + 120 * np.exp(-((hour - 14) ** 2) / 8) * weekday
    noise = np.random.default_rng(seed).normal(0, 8, len(index))
    return pd.Series(np.clip(shape + noise, 5, None), index=index, name="kw")
