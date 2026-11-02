"""Threshold-based peak-shaving controller.

Rule, one interval at a time: if load is above the threshold, discharge to bring it down to
the threshold (as far as power and stored energy allow); if load is below, recharge, but never
so much that net load rises above the threshold. With `ratchet=True`, when the battery cannot
hold the threshold the threshold rises to the new net peak: that month's billing peak is
already set, so there is no point saving energy to defend a lower level.

Two consequences hold by construction and are property-tested:
* net load never exceeds max(original load, threshold), so the battery never raises the
  billing peak when the threshold is at or below the month's peak;
* net load is never negative (no export).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ridgeline.battery.model import battery_limits
from ridgeline.data.schemas import BatterySpec

THRESHOLD_TOL_KW = 0.01


@dataclass(frozen=True)
class Dispatch:
    load_kw: np.ndarray
    charge_kw: np.ndarray
    discharge_kw: np.ndarray
    energy_kwh: np.ndarray  # stored energy at the end of each interval
    initial_energy_kwh: float
    final_threshold_kw: float

    @property
    def net_kw(self) -> np.ndarray:
        return np.asarray(self.load_kw + self.charge_kw - self.discharge_kw, dtype=float)


def idle_dispatch(load_kw: np.ndarray, spec: BatterySpec) -> Dispatch:
    """The battery does nothing (used when dispatch would not pay for itself)."""
    e0 = battery_limits(spec).e_max_kwh
    zeros = np.zeros_like(load_kw, dtype=float)
    return Dispatch(load_kw, zeros, zeros.copy(), np.full(len(load_kw), e0), e0, float("inf"))


def threshold_dispatch(
    load_kw: np.ndarray,
    spec: BatterySpec,
    threshold_kw: float,
    interval_hours: float,
    *,
    ratchet: bool = True,
    initial_energy_kwh: float | None = None,
) -> Dispatch:
    """Run the threshold rule over `load_kw`. The battery starts full unless told otherwise."""
    lim = battery_limits(spec)
    dt = interval_hours
    energy = lim.e_max_kwh if initial_energy_kwh is None else initial_energy_kwh
    e0 = energy
    threshold = threshold_kw
    n = len(load_kw)
    charge, discharge, stored = np.zeros(n), np.zeros(n), np.zeros(n)
    for t in range(n):
        load = float(load_kw[t])
        if load > threshold:
            deliverable = max(energy - lim.e_min_kwh, 0.0) * lim.eta_discharge / dt
            d = min(load - threshold, lim.power_kw, deliverable)
            discharge[t] = d
            energy -= d * dt / lim.eta_discharge
            if ratchet and load - d > threshold:
                threshold = load - d
        else:
            room = max(lim.e_max_kwh - energy, 0.0) / (lim.eta_charge * dt)
            c = min(threshold - load, lim.power_kw, room)
            charge[t] = c
            energy += c * lim.eta_charge * dt
        stored[t] = energy
    return Dispatch(load_kw, charge, discharge, stored, e0, threshold)


def feasible_threshold(
    load_kw: np.ndarray, spec: BatterySpec, interval_hours: float, tol: float = THRESHOLD_TOL_KW
) -> float:
    """Lowest threshold the battery can hold over `load_kw` (bisection, no ratchet).

    Uses the whole series, so it is an oracle when applied to the same period it was computed
    on. The practical controller applies it to the *previous* month instead.
    """
    peak = float(np.max(load_kw))
    lo, hi = max(peak - battery_limits(spec).power_kw, 0.0), peak

    def holds(threshold: float) -> bool:
        run = threshold_dispatch(load_kw, spec, threshold, interval_hours, ratchet=False)
        return float(np.max(run.net_kw)) <= threshold + tol

    if holds(lo):
        return lo
    while hi - lo > tol:
        mid = (lo + hi) / 2
        if holds(mid):
            hi = mid
        else:
            lo = mid
    return hi
