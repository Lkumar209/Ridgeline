"""Golden bills, computed by hand, for the fake fixture tariff."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ridgeline.battery.billing import interval_prices, monthly_bills
from tests.battery_helpers import fixture_tariff


def _constant_january(kw: float) -> pd.Series:
    # Local January 2018: Jan 1 00:00 EST = 05:00 UTC; 31 days of 15-min intervals.
    index = pd.date_range("2018-01-01 05:00", periods=31 * 96, freq="15min", tz="UTC")
    return pd.Series(kw, index=index)


def test_constant_load_january_golden_bill() -> None:
    """100 kW all of January 2018 (23 weekdays, 8 weekend days; Jan 1 is a Monday).

    energy: weekday 08-20 at $0.20 -> 100*12*23*0.20 = 5,520
            weekday other hours at $0.10 -> 100*12*23*0.10 = 2,760
            weekend all day at $0.10 -> 100*24*8*0.10 = 1,920
    flat demand: 100 kW * $10 (January) = 1,000
    TOU demand: on-peak period 100 kW * $5 = 500; off-peak period rate $0
    fixed: 100
    """
    bill = monthly_bills(_constant_january(100.0), fixture_tariff())
    assert list(bill.index) == ["2018-01"]
    row = bill.loc["2018-01"]
    assert row["energy_usd"] == pytest.approx(10_200.0)
    assert row["demand_flat_usd"] == pytest.approx(1_000.0)
    assert row["demand_tou_usd"] == pytest.approx(500.0)
    assert row["fixed_usd"] == 100.0
    assert row["total_usd"] == pytest.approx(11_800.0)
    assert row["energy_kwh"] == pytest.approx(100 * 24 * 31)


def test_tou_demand_uses_peak_within_each_period() -> None:
    load = _constant_january(100.0)
    local = pd.DatetimeIndex(load.index).tz_convert("America/New_York")
    off_peak_spike = (local.day == 3) & (local.hour == 3)  # Wednesday 03:00, off-peak
    load[np.asarray(off_peak_spike)] = 300.0
    row = monthly_bills(load, fixture_tariff()).loc["2018-01"]
    assert row["demand_flat_usd"] == pytest.approx(3_000.0)  # flat charge sees the spike
    assert row["demand_tou_usd"] == pytest.approx(500.0)  # on-peak demand does not


def test_rates_follow_daylight_saving() -> None:
    """2018-07-02 12:00 UTC is 08:00 EDT (on-peak), though 07:00 in standard time."""
    index = pd.DatetimeIndex(["2018-07-02 11:45", "2018-07-02 12:00"], tz="UTC")
    prices = interval_prices(index, fixture_tariff())
    np.testing.assert_allclose(prices.energy_usd_per_kwh, [0.10, 0.20])


def test_flat_demand_rate_changes_by_month() -> None:
    index = pd.DatetimeIndex(["2018-01-15 17:00", "2018-07-15 17:00"], tz="UTC")
    prices = interval_prices(index, fixture_tariff())
    np.testing.assert_allclose(prices.flat_demand_usd_per_kw, [10.0, 12.0])


def test_bills_split_on_local_month_boundaries() -> None:
    """Regression guard: 2018-02-01 03:00 UTC is still January 31 in Boston."""
    index = pd.date_range("2018-01-31 05:00", periods=96 * 2, freq="15min", tz="UTC")
    bills = monthly_bills(pd.Series(50.0, index=index), fixture_tariff())
    assert list(bills.index) == ["2018-01", "2018-02"]
    assert bills["energy_kwh"].tolist() == pytest.approx([50 * 24, 50 * 24])


def test_negative_net_load_is_rejected() -> None:
    load = _constant_january(10.0)
    load.iloc[5] = -1.0
    with pytest.raises(ValueError, match="negative"):
        monthly_bills(load, fixture_tariff())
