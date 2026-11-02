from __future__ import annotations

import numpy as np
import pytest

from ridgeline.scenarios.montecarlo import (
    alive_from_uniform,
    central_draws,
    expected_alive,
    expected_npv,
    run_monte_carlo,
    sample_draws,
    site_randomness,
)
from tests.scenario_helpers import five_sites, inputs


def test_draws_are_reproducible_and_within_ranges() -> None:
    a, b = sample_draws(inputs(), 500, seed=1), sample_draws(inputs(), 500, seed=1)
    np.testing.assert_array_equal(a.capex_usd_per_kw, b.capex_usd_per_kw)
    assert a.proxy_demand_multiplier.min() >= 0.7 and a.proxy_demand_multiplier.max() <= 1.3
    assert not np.array_equal(
        a.capex_usd_per_kw, sample_draws(inputs(), 500, seed=2).capex_usd_per_kw
    )


def test_site_randomness_does_not_depend_on_other_sites() -> None:
    sites = five_sites()
    full = site_randomness(sites, 50, 15, 0.1, seed=3)
    alone = site_randomness([sites[2]], 50, 15, 0.1, seed=3)
    np.testing.assert_array_equal(full.noise[2], alone.noise[0])
    np.testing.assert_array_equal(full.churn_uniform[2], alone.churn_uniform[0])


def test_noise_has_mean_one() -> None:
    noise = site_randomness(five_sites(), 4000, 15, 0.1, seed=4).noise
    assert noise.mean() == pytest.approx(1.0, abs=0.005)


def test_zero_hazard_keeps_tenant_and_higher_hazard_never_lengthens_stay() -> None:
    u = np.random.default_rng(0).uniform(size=(1, 1000))
    assert alive_from_uniform(u, np.zeros((1, 1000)), 15).all()
    low = alive_from_uniform(u, np.full((1, 1000), 0.05), 15)
    high = alive_from_uniform(u, np.full((1, 1000), 0.20), 15)
    assert np.all(high <= low)


def test_sampled_survival_matches_expected_survival() -> None:
    u = np.random.default_rng(1).uniform(size=(1, 20000))
    hazard = np.full((1, 20000), 0.1)
    sampled = alive_from_uniform(u, hazard, 15).mean(axis=1)[0]
    expected = expected_alive(np.full((1, 1), 0.1), 15)[0, 0]
    np.testing.assert_allclose(sampled, expected, atol=0.01)


def test_churn_lowers_npv_when_savings_are_positive() -> None:
    sites, i = five_sites(), inputs()
    draws = sample_draws(i, 300, seed=5)
    rand = site_randomness(sites, 300, i.life_years, i.savings_noise_sd, seed=5)
    with_churn = run_monte_carlo(sites, i, draws, rand)
    without = run_monte_carlo(sites, i, draws, rand, churn=False)
    assert np.all(with_churn <= without + 1e-9)


def test_expected_npv_at_central_values_is_a_single_column() -> None:
    out = expected_npv(five_sites(), inputs(), central_draws(inputs()))
    assert out.shape == (5, 1)
