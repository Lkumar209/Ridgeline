"""Economic invariants of the NPV model (hypothesis)."""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from ridgeline.scenarios.cashflow import Draws, npv

fractions = st.floats(0.0, 0.3)


@st.composite
def draws(draw: st.DrawFn) -> Draws:
    def one(lo: float, hi: float) -> np.ndarray:
        return np.array([draw(st.floats(lo, hi))])

    return Draws(
        capex_usd_per_kw=one(0, 3000),
        om_usd_per_kw_year=one(0, 80),
        discount_rate=one(0.0, 0.15),
        escalation=one(-0.03, 0.05),
        incentive=one(0, 0.5),
        capacity_fade=one(0, 0.05),
        proxy_demand_multiplier=one(0.5, 1.5),
        churn_multiplier=one(0.5, 2.0),
    )


def _npv(d: Draws, demand: float, alive: np.ndarray, proxy: bool = False) -> float:
    years = alive.shape[-1]
    return float(
        npv(
            np.array([demand]),
            np.array([0.0]),
            np.array([proxy]),
            d,
            alive.reshape(1, 1, years),
            np.ones((1, 1, years)),
            power_kw=125.0,
        )[0, 0]
    )


@settings(max_examples=200, deadline=None)
@given(d=draws(), demand=st.floats(0, 20_000), extra=st.floats(1, 500))
def test_npv_falls_with_capex_and_rises_with_savings(d: Draws, demand: float, extra: float) -> None:
    alive = np.ones(15)
    base = _npv(d, demand, alive)
    pricier = Draws(**{**vars(d), "capex_usd_per_kw": d.capex_usd_per_kw + extra})
    assert _npv(pricier, demand, alive) < base
    assert _npv(d, demand + extra, alive) >= base


@settings(max_examples=200, deadline=None)
@given(d=draws(), demand=st.floats(0, 20_000), leave=st.integers(0, 15))
def test_tenant_leaving_never_helps_when_savings_are_non_negative(
    d: Draws, demand: float, leave: int
) -> None:
    stays = np.ones(15)
    leaves = (np.arange(1, 16) < leave + 1).astype(float)
    assert _npv(d, demand, leaves) <= _npv(d, demand, stays) + 1e-6
