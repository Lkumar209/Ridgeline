"""Pydantic models that cross module boundaries.

Sites, load profiles, tariffs and battery specs are validated here once, so downstream code
(gaps, battery, scenarios, ranking) can trust its inputs without re-checking them.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from ridgeline.assumptions import Assumption

LOCAL_TZ = "America/New_York"
MONTHS = 12
HOURS = 24

ParTier = Literal["low", "mid", "high"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Site(_Frozen):
    """One candidate building. All sites are ComStock modeled buildings (see LIMITATIONS.md)."""

    site_id: str
    bldg_id: int
    building_type: str
    county_gisjoin: str
    county_name: str
    tract_gisjoin: str
    utility_eiaid: int | None
    sqft: float = Field(gt=0)
    peak_kw: float = Field(gt=0, description="Annual peak of 15-min average demand")
    mean_kw: float = Field(gt=0)
    par_tier: ParTier
    dev_subset: bool
    data_source: Literal["comstock"] = "comstock"

    @property
    def peak_to_average(self) -> float:
        return self.peak_kw / self.mean_kw

    @property
    def mean_monthly_kwh(self) -> float:
        """Average monthly consumption (annual kWh / 12), used for tariff usage limits."""
        return self.mean_kw * 8760 / 12


class LoadProfile(_Frozen):
    """A regular, gap-free interval load series.

    `start` is the beginning of the first interval, timezone-aware. `kw` holds the average
    demand over each interval. Use `to_series()` to get a pandas Series in local prevailing
    time (America/New_York), which is what tariff windows are defined in.
    """

    site_id: str
    interval_minutes: int = Field(gt=0)
    start: datetime
    kw: list[float] = Field(min_length=1)

    @field_validator("start")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("start must be timezone-aware")
        return v

    @field_validator("kw")
    @classmethod
    def _finite_non_negative(cls, v: list[float]) -> list[float]:
        arr = np.asarray(v, dtype=float)
        if not np.all(np.isfinite(arr)):
            raise ValueError("kw contains NaN or infinite values")
        if np.any(arr < 0):
            raise ValueError("kw contains negative values")
        return v

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.interval_minutes * len(self.kw))

    def to_series(self, tz: str = LOCAL_TZ) -> pd.Series:
        index = pd.date_range(
            start=pd.Timestamp(self.start).tz_convert("UTC"),
            periods=len(self.kw),
            freq=f"{self.interval_minutes}min",
        ).tz_convert(tz)
        return pd.Series(self.kw, index=index, name="kw", dtype=float)

    @classmethod
    def from_series(cls, site_id: str, series: pd.Series) -> LoadProfile:
        """Build from a tz-aware, regularly spaced Series indexed by interval start."""
        index = series.index
        if not isinstance(index, pd.DatetimeIndex) or index.tz is None:
            raise ValueError("series must have a timezone-aware DatetimeIndex")
        if len(index) < 2:
            raise ValueError("series needs at least two points to infer the interval")
        steps = index[1:] - index[:-1]
        if not (steps == steps[0]).all():
            raise ValueError("series index is not regularly spaced")
        # Timedelta arithmetic, not asi8: pandas 3 indexes may be in s/ms/us, not ns.
        minutes = int(steps[0].total_seconds() // 60)
        return cls(
            site_id=site_id,
            interval_minutes=minutes,
            start=index[0].to_pydatetime(),
            kw=[float(x) for x in series.to_numpy()],
        )


class TouSchedule(_Frozen):
    """A URDB-style rate schedule: a price per period, and month x hour maps of period index.

    Weekday/weekend maps are 12 x 24 (month 0 = January, hour 0 = 00:00-01:00 local time).
    """

    rates: list[float] = Field(min_length=1)
    weekday: list[list[int]]
    weekend: list[list[int]]

    @field_validator("rates")
    @classmethod
    def _non_negative(cls, v: list[float]) -> list[float]:
        if any(r < 0 or not math.isfinite(r) for r in v):
            raise ValueError("rates must be finite and non-negative")
        return v

    @model_validator(mode="after")
    def _shapes(self) -> TouSchedule:
        for name, grid in (("weekday", self.weekday), ("weekend", self.weekend)):
            if len(grid) != MONTHS or any(len(row) != HOURS for row in grid):
                raise ValueError(f"{name} schedule must be 12 x 24")
            if any(p < 0 or p >= len(self.rates) for row in grid for p in row):
                raise ValueError(f"{name} schedule references an undefined period")
        return self

    def rate_at(self, month: int, hour: int, is_weekend: bool) -> float:
        """Price for a calendar month (1-12) and local hour (0-23)."""
        grid = self.weekend if is_weekend else self.weekday
        return self.rates[grid[month - 1][hour]]


class Tariff(_Frozen):
    """A commercial electricity tariff, reduced to what the bill calculator needs."""

    tariff_id: str
    utility: str
    eiaid: int | None
    name: str
    source_urls: list[HttpUrl] = Field(min_length=1)
    urdb_uri: HttpUrl | None = None
    effective_date: date | None = None
    fixed_monthly_usd: float = Field(ge=0)
    energy_usd_per_kwh: TouSchedule
    demand_tou_usd_per_kw: TouSchedule | None = None
    flat_demand_usd_per_kw_by_month: list[float] | None = None
    min_peak_kw: float | None = None
    max_peak_kw: float | None = None
    min_monthly_kwh: float | None = None
    max_monthly_kwh: float | None = None
    ratchet_ignored: bool = False
    demand_converted_from_kva_at_pf: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="Set when demand rates were $/kVA and converted to $/kW (rate / PF).",
    )
    is_test_fixture: bool = False

    @field_validator("flat_demand_usd_per_kw_by_month")
    @classmethod
    def _twelve_months(cls, v: list[float] | None) -> list[float] | None:
        if v is not None and (len(v) != MONTHS or any(r < 0 for r in v)):
            raise ValueError("flat demand charges need 12 non-negative monthly values")
        return v

    @model_validator(mode="after")
    def _has_demand_charge(self) -> Tariff:
        if self.demand_tou_usd_per_kw is None and self.flat_demand_usd_per_kw_by_month is None:
            raise ValueError("tariff has no demand charge; peak shaving would have no value")
        return self

    def is_eligible(self, peak_kw: float, monthly_kwh: float) -> bool:
        """Both the demand limits and the monthly-usage limits must hold (None = no limit)."""

        def within(value: float, lo: float | None, hi: float | None) -> bool:
            low = lo if lo is not None else -math.inf
            high = hi if hi is not None else math.inf
            return low <= value <= high

        return within(peak_kw, self.min_peak_kw, self.max_peak_kw) and within(
            monthly_kwh, self.min_monthly_kwh, self.max_monthly_kwh
        )


class BatterySpec(_Frozen):
    power_kw: float = Field(gt=0)
    energy_kwh: float = Field(gt=0)
    round_trip_efficiency: float = Field(gt=0, le=1)
    soc_min: float = Field(ge=0, lt=1)
    soc_max: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def _soc_order(self) -> BatterySpec:
        if self.soc_min >= self.soc_max:
            raise ValueError("soc_min must be below soc_max")
        return self

    @classmethod
    def from_assumptions(cls, a: dict[str, Assumption]) -> BatterySpec:
        def num(key: str) -> float:
            value = a[key].value
            if isinstance(value, str):
                raise ValueError(f"assumption {key} must be numeric")
            return float(value)

        return cls(
            power_kw=num("battery_power_kw"),
            energy_kwh=num("battery_energy_kwh"),
            round_trip_efficiency=num("battery_round_trip_efficiency"),
            soc_min=num("battery_soc_min"),
            soc_max=num("battery_soc_max"),
        )
