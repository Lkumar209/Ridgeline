"""Perfect-foresight dispatch: the bill-minimizing schedule for one month, as a linear program.

This is an upper bound on what any controller could save with the same battery model, start
state (full) and tariff, because it sees the whole month in advance. The practical controller's
savings divided by this bound is the "capture ratio".

Variables per interval t: charge c_t, discharge d_t, stored energy e_t. Plus one billing-demand
variable for the flat charge and one per TOU demand period.

    minimize   sum_t dt * price_t * (c_t - d_t) + flat_rate * D + sum_p tou_rate_p * D_p
    subject to e_t = e_{t-1} + eta_c * dt * c_t - dt / eta_d * d_t      (e_{-1} = e_max)
               load_t + c_t - d_t <= D                  (every t)
               load_t + c_t - d_t <= D_p                (t in TOU period p)
               d_t - c_t <= load_t                      (no export)
               0 <= c_t, d_t <= P;   e_min <= e_t <= e_max;   D, D_p >= 0

Solved with HiGHS via scipy.optimize.linprog (sparse). A month (~3,000 intervals) solves in well
under a second.
"""

from __future__ import annotations

import numpy as np
import scipy.sparse as sp
from scipy.optimize import linprog

from ridgeline.battery.billing import IntervalPrices
from ridgeline.battery.dispatch import Dispatch
from ridgeline.battery.model import battery_limits
from ridgeline.data.schemas import BatterySpec


class OptimizationError(RuntimeError):
    """The LP solver did not return an optimal solution."""


def optimal_dispatch(
    load_kw: np.ndarray,
    prices: IntervalPrices,
    rows: np.ndarray,
    spec: BatterySpec,
    interval_hours: float,
) -> Dispatch:
    """Bill-minimizing dispatch over the intervals selected by `rows` (one billing month).

    The LP may charge and discharge in the same interval when that is cost-neutral (it only
    burns energy as losses); this does not change the bill and is left as solved.
    """
    lim = battery_limits(spec)
    dt = interval_hours
    load = np.asarray(load_kw, dtype=float)
    n = len(load)
    energy_price = prices.energy_usd_per_kwh[rows]
    flat_rate = float(prices.flat_demand_usd_per_kw[rows][0])
    tou_period = None if prices.tou_period is None else prices.tou_period[rows]
    tou_ids = [] if tou_period is None else sorted(int(p) for p in np.unique(tou_period))
    k = len(tou_ids)

    # Variable layout: [c (n) | d (n) | e (n) | D (1) | D_p (k)]
    i_c, i_d, i_dem = 0, n, 3 * n  # energy block e sits at [2n, 3n)
    n_vars = 3 * n + 1 + k
    cost = np.zeros(n_vars)
    cost[i_c : i_c + n] = dt * energy_price
    cost[i_d : i_d + n] = -dt * energy_price
    cost[i_dem] = flat_rate
    for j, p in enumerate(tou_ids):
        cost[i_dem + 1 + j] = float(prices.tou_rates[p])

    eye = sp.identity(n, format="csr")
    shift = sp.eye(n, k=-1, format="csr")  # picks e_{t-1}
    a_eq = sp.hstack(
        [
            -lim.eta_charge * dt * eye,
            (dt / lim.eta_discharge) * eye,
            eye - shift,
            sp.csr_matrix((n, 1 + k)),
        ]
    )
    b_eq = np.zeros(n)
    b_eq[0] = lim.e_max_kwh  # e_0 - e_max = eta_c dt c_0 - dt/eta_d d_0

    blocks = [
        # c - d - D <= -load
        sp.hstack(
            [
                eye,
                -eye,
                sp.csr_matrix((n, n)),
                -sp.csr_matrix(np.ones((n, 1))),
                sp.csr_matrix((n, k)),
            ]
        ),
        # d - c <= load
        sp.hstack([-eye, eye, sp.csr_matrix((n, n + 1 + k))]),
    ]
    rhs = [-load, load]
    for j, p in enumerate(tou_ids):
        member = np.flatnonzero(tou_period == p)
        pick = sp.csr_matrix(
            (np.ones(len(member)), (np.arange(len(member)), member)), shape=(len(member), n)
        )
        d_col = sp.csr_matrix(
            (np.ones(len(member)), (np.arange(len(member)), np.full(len(member), 1 + j))),
            shape=(len(member), 1 + k),
        )
        blocks.append(sp.hstack([pick, -pick, sp.csr_matrix((len(member), n)), -d_col]))
        rhs.append(-load[member])
    a_ub = sp.vstack(blocks).tocsr()
    b_ub = np.concatenate(rhs)

    bounds = (
        [(0.0, lim.power_kw)] * (2 * n)
        + [(lim.e_min_kwh, lim.e_max_kwh)] * n
        + [(0.0, None)] * (1 + k)
    )
    # scipy-stubs types A_ub/A_eq as dense arrays; HiGHS accepts sparse matrices at runtime.
    result = linprog(  # type: ignore[call-overload]
        cost, A_ub=a_ub, b_ub=b_ub, A_eq=a_eq.tocsr(), b_eq=b_eq, bounds=bounds, method="highs"
    )
    if result.status != 0:
        raise OptimizationError(f"LP failed: {result.message}")
    x = np.asarray(result.x, dtype=float)
    charge = np.clip(x[i_c : i_c + n], 0.0, lim.power_kw)
    discharge = np.clip(x[i_d : i_d + n], 0.0, lim.power_kw)
    # Enforce no-export exactly: net = (load + c) - min(d, load + c) >= 0 in floating point.
    # Regression: an earlier post-processing step (cancelling simultaneous c and d) produced
    # net = -1.6e-15 by cancellation, which billing rejected. Found by the property test.
    discharge = np.minimum(discharge, load + charge)
    energy = _replay_energy(charge, discharge, lim.e_max_kwh, lim.eta_charge, lim.eta_discharge, dt)
    return Dispatch(load, charge, discharge, energy, lim.e_max_kwh, float("nan"))


def _replay_energy(
    charge: np.ndarray, discharge: np.ndarray, e0: float, eta_c: float, eta_d: float, dt: float
) -> np.ndarray:
    """Stored energy implied by a charge/discharge schedule (exact battery bookkeeping)."""
    return np.asarray(e0 + np.cumsum(eta_c * dt * charge - dt / eta_d * discharge), dtype=float)
