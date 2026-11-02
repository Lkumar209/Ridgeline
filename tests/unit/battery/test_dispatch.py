from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from ridgeline.battery.billing import interval_prices
from ridgeline.battery.dispatch import feasible_threshold, idle_dispatch, threshold_dispatch
from ridgeline.battery.model import battery_limits
from ridgeline.battery.optimal import optimal_dispatch
from ridgeline.data.schemas import BatterySpec
from tests.battery_helpers import SPEC, fixture_tariff, office_like_load

DT = 0.25


def test_efficiency_split_reproduces_round_trip() -> None:
    lim = battery_limits(SPEC)
    assert lim.eta_charge * lim.eta_discharge == pytest.approx(0.88)
    assert (lim.e_min_kwh, lim.e_max_kwh) == pytest.approx((12.5, 237.5))


def test_shaves_a_single_spike_to_the_threshold() -> None:
    load = np.array([100.0, 100.0, 180.0, 100.0])
    run = threshold_dispatch(load, SPEC, threshold_kw=150.0, interval_hours=DT)
    assert run.discharge_kw[2] == pytest.approx(30.0)
    assert run.net_kw[2] == pytest.approx(150.0)
    # Recharge replaces exactly what was used, grossed up for round-trip losses.
    assert run.charge_kw[3] == pytest.approx(30.0 / 0.88)
    assert run.energy_kwh[3] == pytest.approx(battery_limits(SPEC).e_max_kwh)


def test_recharge_never_pushes_net_above_threshold() -> None:
    load = np.array([100.0, 200.0, 140.0])
    run = threshold_dispatch(load, SPEC, threshold_kw=150.0, interval_hours=DT)
    assert run.net_kw[2] == pytest.approx(150.0)  # charge capped at 10 kW by the threshold


def test_power_limit_caps_shaving() -> None:
    load = np.array([400.0])
    run = threshold_dispatch(load, SPEC, threshold_kw=100.0, interval_hours=DT, ratchet=False)
    assert run.discharge_kw[0] == pytest.approx(125.0)


def test_empty_battery_cannot_discharge() -> None:
    lim = battery_limits(SPEC)
    run = threshold_dispatch(np.array([300.0]), SPEC, 100.0, DT, initial_energy_kwh=lim.e_min_kwh)
    assert run.discharge_kw[0] == 0.0
    assert run.final_threshold_kw == 300.0  # ratcheted to the unavoidable peak


def test_ratchet_raises_threshold_once_breached() -> None:
    # Battery can hold 150 only for ~1 h of 225 kWh usable at 75 kW deficit... then breaks.
    load = np.full(40, 225.0)
    run = threshold_dispatch(load, SPEC, 150.0, DT)
    assert run.final_threshold_kw > 150.0
    assert run.net_kw.max() == pytest.approx(run.final_threshold_kw)


def test_threshold_above_peak_means_no_action() -> None:
    load = office_like_load(3).to_numpy()
    run = threshold_dispatch(load, SPEC, float(load.max()) + 1, DT)
    assert run.discharge_kw.sum() == 0.0
    assert run.charge_kw.sum() == 0.0  # starts full, nothing to recharge


def test_feasible_threshold_is_tight() -> None:
    load = office_like_load(7, seed=3).to_numpy()
    t = feasible_threshold(load, SPEC, DT)
    held = threshold_dispatch(load, SPEC, t, DT, ratchet=False)
    assert held.net_kw.max() <= t + 0.01
    lower = threshold_dispatch(load, SPEC, t - 0.05, DT, ratchet=False)
    assert lower.net_kw.max() > t - 0.05 + 0.01
    assert t >= load.max() - SPEC.power_kw


def test_idle_dispatch_changes_nothing() -> None:
    load = office_like_load(1).to_numpy()
    run = idle_dispatch(load, SPEC)
    np.testing.assert_array_equal(run.net_kw, load)
    assert math.isinf(run.final_threshold_kw)


def test_optimal_never_exports_with_tiny_loads() -> None:
    """Regression (found by hypothesis): cancelling simultaneous charge/discharge in
    post-processing gave net = 17 - 16.99 - 0.01 = -1.6e-15 kW, which billing rejects as export."""
    spec = BatterySpec(
        power_kw=17.0, energy_kwh=5.0, round_trip_efficiency=0.75, soc_min=0.0, soc_max=1.0
    )
    load = np.array([0.0, 0.01, 0.0, 0.0])
    index = pd.date_range("2018-03-05 05:00", periods=4, freq="15min", tz="UTC")
    prices = interval_prices(index, fixture_tariff())
    run = optimal_dispatch(load, prices, np.arange(4), spec, DT)
    assert run.net_kw.min() >= 0.0
