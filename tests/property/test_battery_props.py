"""Physical and billing invariants of every dispatch method (hypothesis)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from ridgeline.battery.billing import interval_prices
from ridgeline.battery.dispatch import Dispatch, threshold_dispatch
from ridgeline.battery.model import battery_limits
from ridgeline.battery.optimal import optimal_dispatch
from ridgeline.battery.simulate import simulate_site
from ridgeline.data.schemas import BatterySpec
from tests.battery_helpers import fixture_tariff, flat_demand_tariff

DT = 0.25
TOL = 1e-6

specs = st.builds(
    BatterySpec,
    power_kw=st.floats(5, 300),
    energy_kwh=st.floats(5, 600),
    round_trip_efficiency=st.floats(0.6, 1.0),
    soc_min=st.floats(0.0, 0.3),
    soc_max=st.floats(0.7, 1.0),
)
loads = st.lists(st.floats(0, 800, allow_nan=False), min_size=4, max_size=300).map(np.array)


def assert_physical(run: Dispatch, spec: BatterySpec, *, exclusive: bool = True) -> None:
    lim = battery_limits(spec)
    # State of charge stays within bounds.
    assert run.energy_kwh.min() >= lim.e_min_kwh - TOL
    assert run.energy_kwh.max() <= lim.e_max_kwh + TOL
    # Power limits and no simultaneous charge and discharge.
    assert run.charge_kw.min() >= -TOL and run.discharge_kw.min() >= -TOL
    assert run.charge_kw.max() <= lim.power_kw + TOL
    assert run.discharge_kw.max() <= lim.power_kw + TOL
    if exclusive:  # the threshold rule never charges and discharges at once
        assert np.all(np.minimum(run.charge_kw, run.discharge_kw) <= TOL)
    # Energy conservation with losses: stored change = eta_c*in - out/eta_d.
    stored_in = lim.eta_charge * DT * run.charge_kw.sum()
    stored_out = DT / lim.eta_discharge * run.discharge_kw.sum()
    assert abs(run.energy_kwh[-1] - run.initial_energy_kwh - (stored_in - stored_out)) < 1e-6
    # Losses are non-negative: grid energy in >= energy delivered + stored gain.
    grid_in, delivered = DT * run.charge_kw.sum(), DT * run.discharge_kw.sum()
    assert grid_in - delivered >= (run.energy_kwh[-1] - run.initial_energy_kwh) - 1e-6
    # No export.
    assert run.net_kw.min() >= -TOL


@settings(max_examples=200, deadline=None)
@given(load=loads, spec=specs, frac=st.floats(0.0, 1.2), ratchet=st.booleans())
def test_threshold_controller_invariants(
    load: np.ndarray, spec: BatterySpec, frac: float, ratchet: bool
) -> None:
    threshold = frac * float(load.max())
    run = threshold_dispatch(load, spec, threshold, DT, ratchet=ratchet)
    assert_physical(run, spec)
    # Never raises the billing peak, and never pushes net above max(load, threshold).
    assert run.net_kw.max() <= load.max() + TOL
    assert np.all(run.net_kw <= np.maximum(load, run.final_threshold_kw) + TOL)


def _month_index(n: int) -> pd.DatetimeIndex:
    return pd.date_range("2018-03-05 05:00", periods=n, freq="15min", tz="UTC")


@settings(max_examples=25, deadline=None)
@given(load=loads, spec=specs, flat=st.booleans())
def test_optimal_dispatch_is_physical_and_never_worse(
    load: np.ndarray, spec: BatterySpec, flat: bool
) -> None:
    assume(load.max() > 0)
    tariff = flat_demand_tariff() if flat else fixture_tariff()
    index = _month_index(len(load))
    prices = interval_prices(index, tariff)
    rows = np.arange(len(load))
    run = optimal_dispatch(load, prices, rows, spec, DT)
    assert_physical(run, spec, exclusive=False)
    sim = simulate_site(pd.Series(load, index=index), tariff, spec)
    for strategy in ("practical", "oracle", "optimal"):
        # Bill with battery <= bill without, every month, every strategy.
        assert (sim[f"{strategy}_bill_usd"] <= sim["base_bill_usd"] + TOL).all()
        # The battery never raises the billing peak.
        assert (sim[f"{strategy}_peak_kw"] <= sim["base_peak_kw"] + TOL).all()
    # Perfect foresight is a lower bound on the bill for any controller.
    for strategy in ("practical", "oracle"):
        assert (sim["optimal_bill_usd"] <= sim[f"{strategy}_bill_usd"] + 1e-4).all()
