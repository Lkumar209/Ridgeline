"""Monthly bills from a net-load series and a tariff.

Bills are computed per local calendar month (a stand-in for the billing cycle):

    energy  = sum_t kW_t * dt * energy_rate_t
    flat    = max_t kW_t * flat_demand_rate[month]
    tou     = sum_p max_{t in p} kW_t * tou_demand_rate[p]
    fixed   = monthly fixed charge

All rates are looked up in local wall-clock time (America/New_York). Holidays are billed as
ordinary weekdays (LIMITATIONS.md).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ridgeline.data.schemas import LOCAL_TZ, Tariff, TouSchedule

BILL_COLUMNS = [
    "peak_kw",
    "energy_kwh",
    "energy_usd",
    "demand_flat_usd",
    "demand_tou_usd",
    "fixed_usd",
    "total_usd",
]


@dataclass(frozen=True)
class IntervalPrices:
    """A tariff unrolled onto one interval index, so billing and optimization are vectorized."""

    energy_usd_per_kwh: np.ndarray
    flat_demand_usd_per_kw: np.ndarray  # the interval's month rate; zeros if no flat charge
    tou_period: np.ndarray | None  # TOU demand period index per interval
    tou_rates: np.ndarray  # $/kW per TOU demand period (empty if none)
    month: pd.PeriodIndex  # local calendar month of each interval


def _calendar(index: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    local = index.tz_convert(LOCAL_TZ)
    return (
        np.asarray(local.month, dtype=np.int64),
        np.asarray(local.hour, dtype=np.int64),
        np.asarray(local.day_of_week >= 5, dtype=bool),
    )


def _periods(
    schedule: TouSchedule, month: np.ndarray, hour: np.ndarray, weekend: np.ndarray
) -> np.ndarray:
    weekday_grid = np.asarray(schedule.weekday)
    weekend_grid = np.asarray(schedule.weekend)
    chosen = np.where(weekend, weekend_grid[month - 1, hour], weekday_grid[month - 1, hour])
    return np.asarray(chosen, dtype=np.int64)


def interval_prices(index: pd.DatetimeIndex, tariff: Tariff) -> IntervalPrices:
    month, hour, weekend = _calendar(index)
    energy_period = _periods(tariff.energy_usd_per_kwh, month, hour, weekend)
    energy = np.asarray(tariff.energy_usd_per_kwh.rates)[energy_period]
    if tariff.flat_demand_usd_per_kw_by_month is None:
        flat = np.zeros(len(index))
    else:
        flat = np.asarray(tariff.flat_demand_usd_per_kw_by_month)[month - 1]
    tou = tariff.demand_tou_usd_per_kw
    tou_period = None if tou is None else _periods(tou, month, hour, weekend)
    tou_rates = np.asarray([] if tou is None else tou.rates, dtype=float)
    local_month = index.tz_convert(LOCAL_TZ).tz_localize(None).to_period("M")
    return IntervalPrices(energy, flat, tou_period, tou_rates, local_month)


def month_bill(
    net_kw: np.ndarray,
    prices: IntervalPrices,
    rows: np.ndarray,
    interval_hours: float,
    fixed_usd: float,
) -> dict[str, float]:
    """Bill for the intervals selected by `rows` (all in one month)."""
    kw = net_kw[rows]
    if np.any(kw < 0):
        raise ValueError("net load is negative; exports are not modeled")
    energy_usd = float(np.sum(kw * interval_hours * prices.energy_usd_per_kwh[rows]))
    peak = float(kw.max())
    flat_usd = peak * float(prices.flat_demand_usd_per_kw[rows][0])
    tou_usd = 0.0
    if prices.tou_period is not None:
        periods = prices.tou_period[rows]
        for p in np.unique(periods):
            tou_usd += float(kw[periods == p].max()) * float(prices.tou_rates[p])
    return {
        "peak_kw": peak,
        "energy_kwh": float(kw.sum() * interval_hours),
        "energy_usd": energy_usd,
        "demand_flat_usd": flat_usd,
        "demand_tou_usd": tou_usd,
        "fixed_usd": fixed_usd,
        "total_usd": energy_usd + flat_usd + tou_usd + fixed_usd,
    }


def monthly_bills(net_kw: pd.Series, tariff: Tariff) -> pd.DataFrame:
    """One row per local calendar month, columns `BILL_COLUMNS`."""
    index = pd.DatetimeIndex(net_kw.index)
    hours = (index[1] - index[0]).total_seconds() / 3600
    prices = interval_prices(index, tariff)
    values = net_kw.to_numpy(dtype=float)
    rows = {
        str(m): month_bill(values, prices, prices.month == m, hours, tariff.fixed_monthly_usd)
        for m in prices.month.unique()
    }
    frame = pd.DataFrame.from_dict(rows, orient="index", columns=BILL_COLUMNS)
    frame.index.name = "month"
    return frame
