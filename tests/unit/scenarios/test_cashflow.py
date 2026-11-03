from __future__ import annotations

import numpy as np
import pytest

from ridgeline.scenarios.cashflow import Draws, npv


def _draws(n: int = 1, **values: float) -> Draws:
    base = {
        "capex_usd_per_kw": 1000.0,
        "om_usd_per_kw_year": 20.0,
        "discount_rate": 0.10,
        "escalation": 0.0,
        "incentive": 0.0,
        "capacity_fade": 0.0,
        "proxy_demand_multiplier": 1.0,
        "churn_multiplier": 1.0,
    }
    base.update(values)
    return Draws(**{k: np.full(n, v) for k, v in base.items()})


def _run(
    draws: Draws, alive: float = 1.0, years: int = 2, proxy: bool = False, demand: float = 5000.0
) -> float:
    shape = (1, draws.n, years)
    return float(
        npv(
            np.array([demand]),
            np.array([-200.0]),
            np.array([proxy]),
            draws,
            np.full(shape, alive),
            np.ones(shape),
            power_kw=10.0,
        )[0, 0]
    )


def test_hand_computed_two_year_npv() -> None:
    """capex 10 kW x $1000 = 10,000; yearly net = 5000 - 200 - 10 x 20 = 4,600; r = 10%.

    NPV = -10,000 + 4,600/1.1 + 4,600/1.21 = -10,000 + 4,181.82 + 3,801.65 = -2,016.53
    """
    assert _run(_draws()) == pytest.approx(-2016.53, abs=0.01)


def test_incentive_reduces_upfront_cost() -> None:
    assert _run(_draws(incentive=0.3)) - _run(_draws()) == pytest.approx(3000.0)


def test_departed_tenant_stops_savings_but_not_om() -> None:
    """With alive = 0 only O&M remains: -10,000 - 200/1.1 - 200/1.21."""
    assert _run(_draws(), alive=0.0) == pytest.approx(-10000 - 200 / 1.1 - 200 / 1.21)


def test_proxy_multiplier_applies_to_proxy_sites_only() -> None:
    d = _draws(proxy_demand_multiplier=1.3)
    assert _run(d, proxy=False) == pytest.approx(_run(_draws(), proxy=False))
    expected_gain = 0.3 * 5000 * (1 / 1.1 + 1 / 1.21)
    assert _run(d, proxy=True) - _run(_draws(), proxy=True) == pytest.approx(expected_gain)


def test_fade_and_escalation_compound_from_year_two() -> None:
    faded = _run(_draws(capacity_fade=0.5))
    # Year 1 savings untouched; year 2 savings (4,800) halved.
    assert _run(_draws()) - faded == pytest.approx(0.5 * 4800 / 1.21)


def test_shape_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="shape mismatch"):
        npv(
            np.ones(2),
            np.ones(2),
            np.zeros(2, bool),
            _draws(),
            np.ones((1, 1, 2)),
            np.ones((1, 1, 2)),
            1.0,
        )
