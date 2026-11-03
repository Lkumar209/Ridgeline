"""Vectorized 15-year NPV for many sites x many draws (pure numpy).

For site s, draw n and year t = 1..T:

    savings[s,n,t] = (m[s,n] * D[s] + E[s]) * (1+g[n])^(t-1) * (1-f[n])^(t-1) * noise[s,n,t]
    NPV[s,n] = -capex[n] * P * (1 - incentive[n])
               + sum_t (alive[s,n,t] * savings[s,n,t] - om[n] * P) / (1 + r[n])^t

D and E are year-1 demand and energy savings from the dispatch simulation; m multiplies demand
savings for proxy-tariff sites only; g is real tariff escalation; f is capacity fade (savings
assumed proportional to remaining capacity); alive is 1 while the tenant stays (or the survival
probability, for expected-value runs). When the tenant leaves, the savings stop but the fixed
O&M contract runs to the end of the project: the battery stays with the building.
The same function serves the Monte Carlo (many draws) and the deterministic tornado (one draw at
central values).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True)
class Draws:
    """Global inputs, one value per draw (shape (N,)), shared by all sites."""

    capex_usd_per_kw: np.ndarray
    om_usd_per_kw_year: np.ndarray
    discount_rate: np.ndarray
    escalation: np.ndarray
    incentive: np.ndarray
    capacity_fade: np.ndarray
    proxy_demand_multiplier: np.ndarray
    churn_multiplier: np.ndarray

    @property
    def n(self) -> int:
        return len(self.capex_usd_per_kw)

    def with_value(self, name: str, value: float) -> Draws:
        """Copy with one input pinned to `value` in every draw."""
        return replace(self, **{name: np.full(self.n, value)})


def npv(
    demand_savings: np.ndarray,
    energy_savings: np.ndarray,
    is_proxy: np.ndarray,
    draws: Draws,
    alive: np.ndarray,
    noise: np.ndarray,
    power_kw: float,
) -> np.ndarray:
    """NPV per site and draw, shape (S, N). `alive` and `noise` have shape (S, N, T)."""
    s, n, t_max = alive.shape
    if noise.shape != alive.shape or draws.n != n or len(demand_savings) != s:
        raise ValueError("shape mismatch between sites, draws and years")
    years = np.arange(1, t_max + 1)[None, None, :]
    growth = (1 + draws.escalation)[None, :, None] ** (years - 1)
    capacity = (1 - draws.capacity_fade)[None, :, None] ** (years - 1)
    multiplier = np.where(is_proxy[:, None], draws.proxy_demand_multiplier[None, :], 1.0)
    year1 = multiplier * demand_savings[:, None] + energy_savings[:, None]  # (S, N)
    savings = year1[:, :, None] * growth * capacity * noise
    om = (draws.om_usd_per_kw_year * power_kw)[None, :, None]
    discount = (1 + draws.discount_rate)[None, :, None] ** (-years)
    capex = draws.capex_usd_per_kw * power_kw * (1 - draws.incentive)
    return np.asarray(-capex[None, :] + np.sum((alive * savings - om) * discount, axis=2))


def annuity_factor(discount_rate: np.ndarray, years: int) -> np.ndarray:
    """Present value of $1 a year for `years` years, per draw: sum_t (1 + r)^-t. Shape (N,)."""
    t = np.arange(1, years + 1)[None, :]
    return np.asarray(np.sum((1 + discount_rate)[:, None] ** (-t), axis=1))
