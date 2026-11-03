"""Seeded Monte Carlo over the economic inputs and per-site churn and noise.

Global inputs are drawn once and shared by all sites (common random numbers), so differences
between sites come from the sites, not from sampling luck. Per-site randomness is seeded by
(seed, bldg_id), so a site's draws do not depend on which other sites are in the run.

Churn uses fixed uniforms per site and draw, turned into a departure year by inverse CDF. That
way "churn on" and "churn off", or different churn multipliers, compare like with like.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ridgeline.scenarios.cashflow import Draws, discounted_cashflows, npv
from ridgeline.scenarios.inputs import EconomicInputs, SiteEconomics


def sample_draws(inputs: EconomicInputs, n: int, seed: int) -> Draws:
    """Uniform draws between each input's low and high."""
    rng = np.random.default_rng([seed, 0])
    fields = {}
    for name in EconomicInputs.UNCERTAIN:
        r = getattr(inputs, name)
        fields[name] = rng.uniform(r.low, r.high, n)
    return Draws(**fields)


def central_draws(inputs: EconomicInputs) -> Draws:
    """A single 'draw' with every input at its central value."""
    return Draws(
        **{name: np.array([getattr(inputs, name).central]) for name in EconomicInputs.UNCERTAIN}
    )


@dataclass(frozen=True)
class SiteRandomness:
    churn_uniform: np.ndarray  # (S, N), U(0,1) for the departure year
    noise: np.ndarray  # (S, N, T), multiplicative savings noise, mean 1


def site_randomness(
    sites: list[SiteEconomics], n: int, years: int, noise_sd: float, seed: int
) -> SiteRandomness:
    uniforms, noises = [], []
    for site in sites:
        rng = np.random.default_rng([seed, 1, site.bldg_id])
        uniforms.append(rng.uniform(0.0, 1.0, n))
        normal = rng.normal(-0.5 * noise_sd**2, noise_sd, (n, years))
        noises.append(np.exp(normal))  # lognormal with mean 1
    return SiteRandomness(np.stack(uniforms), np.stack(noises))


def alive_from_uniform(uniform: np.ndarray, hazard: np.ndarray, years: int) -> np.ndarray:
    """1.0 for years before the tenant leaves, 0.0 from the departure year on. Shape (S, N, T).

    The departure year K is geometric(p): P(K > t) = (1-p)^t. Inverse CDF of a fixed uniform,
    so a higher hazard can only make the tenant leave earlier.
    """
    p = np.clip(hazard, 0.0, 1.0)
    with np.errstate(divide="ignore"):
        k = np.where(
            p > 0, np.ceil(np.log1p(-uniform) / np.log1p(-np.minimum(p, 1 - 1e-12))), np.inf
        )
    t = np.arange(1, years + 1)[None, None, :]
    return np.asarray(t < k[:, :, None], dtype=float)


def expected_alive(hazard: np.ndarray, years: int) -> np.ndarray:
    """Survival probability P(still there in year t) = (1-p)^t, for expected-value runs."""
    t = np.arange(1, years + 1)[None, None, :]
    return np.asarray((1 - np.clip(hazard, 0, 1))[:, :, None] ** t)


def run_monte_carlo(
    sites: list[SiteEconomics],
    inputs: EconomicInputs,
    draws: Draws,
    randomness: SiteRandomness,
    *,
    churn: bool = True,
) -> np.ndarray:
    """NPV per site and draw, shape (S, N)."""
    years = inputs.life_years
    base_hazard = np.array([s.churn_hazard for s in sites])
    hazard = (
        base_hazard[:, None] * draws.churn_multiplier[None, :]
        if churn
        else np.zeros((len(sites), draws.n))
    )
    alive = alive_from_uniform(randomness.churn_uniform, hazard, years)
    return npv(*_site_arrays(sites), draws, alive, randomness.noise, inputs.power_kw)


def cashflow_fan(
    sites: list[SiteEconomics],
    inputs: EconomicInputs,
    draws: Draws,
    randomness: SiteRandomness,
) -> np.ndarray:
    """P10/P50/P90 of cumulative discounted cash flow by year, shape (S, 3, T+1).

    Same draws and churn as `run_monte_carlo`, so the last year equals the NPV percentiles.
    """
    years = inputs.life_years
    hazard = np.array([s.churn_hazard for s in sites])[:, None] * draws.churn_multiplier[None, :]
    alive = alive_from_uniform(randomness.churn_uniform, hazard, years)
    flows = discounted_cashflows(
        *_site_arrays(sites), draws, alive, randomness.noise, inputs.power_kw
    )
    cumulative = np.cumsum(flows, axis=2)
    return np.asarray(np.percentile(cumulative, [10, 50, 90], axis=1).transpose(1, 0, 2))


def expected_npv(sites: list[SiteEconomics], inputs: EconomicInputs, draws: Draws) -> np.ndarray:
    """Deterministic NPV (no noise, expected survival) for each site and draw, shape (S, N)."""
    years = inputs.life_years
    hazard = np.array([s.churn_hazard for s in sites])[:, None] * draws.churn_multiplier[None, :]
    alive = expected_alive(hazard, years)
    noise = np.ones((len(sites), draws.n, years))
    return npv(*_site_arrays(sites), draws, alive, noise, inputs.power_kw)


def _site_arrays(sites: list[SiteEconomics]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.array([s.demand_savings_usd for s in sites]),
        np.array([s.energy_savings_usd for s in sites]),
        np.array([s.tariff_is_proxy for s in sites]),
    )
