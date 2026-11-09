"""Simulate one site for one year, month by month, under several dispatch strategies.

Each billing month is simulated independently, with the battery starting full (DECISIONS.md
ADR-008). Strategies:

* ``base``: no battery.
* ``practical``: the threshold controller. Its starting threshold is the lowest threshold
  the battery could have held over the *previous* month (persistence: history only, no
  foresight), and it ratchets up when breached. The first month of the data has no history,
  so by default (``history="causal"``) the practical battery stays idle that month.
  ``history="wraparound"`` instead uses the *last* month of the same data year for the first
  month. That is a lookahead (future information), kept only for comparison.
* ``oracle``: the same controller with the lowest feasible threshold for the month itself.
  This is a diagnostic: it isolates the cost of not knowing the threshold.
* ``optimal``: the perfect-foresight LP (`battery/optimal.py`), an upper bound on savings.

An operator can always leave the battery idle. If a controller's month would cost more than
no battery (round-trip losses outweighing demand savings), that month is billed as idle and
flagged. So the bill with a battery is never above the bill without one, by construction.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from ridgeline.battery.billing import demand_billed, interval_prices, month_bill
from ridgeline.battery.dispatch import (
    Dispatch,
    feasible_threshold,
    idle_dispatch,
    threshold_dispatch,
)
from ridgeline.battery.optimal import optimal_dispatch
from ridgeline.data.schemas import BatterySpec, Site, Tariff

STRATEGIES = ("base", "practical", "oracle", "optimal")
COST_TOL_USD = 1e-6
History = Literal["causal", "wraparound"]


def simulate_site(
    load_kw: pd.Series,
    tariff: Tariff,
    spec: BatterySpec,
    *,
    with_optimal: bool = True,
    history: History = "causal",
) -> pd.DataFrame:
    """One row per local month with peaks, bills and flags for each strategy."""
    index = pd.DatetimeIndex(load_kw.index)
    dt = (index[1] - index[0]).total_seconds() / 3600
    prices = interval_prices(index, tariff)
    billed = demand_billed(prices)
    values = load_kw.to_numpy(dtype=float)
    months = list(prices.month.unique())
    rows_by_month = [np.flatnonzero(prices.month == m) for m in months]

    records = []
    for i, (month, rows) in enumerate(zip(months, rows_by_month, strict=True)):
        load = values[rows]
        # Month 0 has no history. "wraparound" borrows the last month of the year (lookahead).
        has_history = i > 0 or history == "wraparound"
        previous = values[rows_by_month[i - 1]] if has_history else None
        previous_billed = billed[rows_by_month[i - 1]] if has_history else None
        month_billed = billed[rows]

        def bill(net: np.ndarray, rows: np.ndarray = rows) -> Bill:
            full = np.zeros(len(values))
            full[rows] = net
            parts = month_bill(full, prices, rows, dt, tariff.fixed_monthly_usd)
            return Bill(
                total=parts["total_usd"],
                demand=parts["demand_flat_usd"] + parts["demand_tou_usd"],
                energy=parts["energy_usd"],
            )

        base = bill(load)
        base_bill = base.total
        if previous is None:
            start_threshold = float("nan")
            practical = idle_dispatch(load, spec)
        else:
            start_threshold = feasible_threshold(previous, spec, dt, billed=previous_billed)
            practical = threshold_dispatch(load, spec, start_threshold, dt, billed=month_billed)
        record: dict[str, object] = {
            "month": str(month),
            "practical_start_threshold_kw": start_threshold,
            "practical_no_history": previous is None,
            "practical_history_is_lookahead": i == 0 and history == "wraparound",
            "base_peak_kw": float(load.max()),
            "base_bill_usd": base_bill,
            "base_demand_usd": base.demand,
            "base_energy_usd": base.energy,
        }
        dispatches: dict[str, Dispatch] = {
            "practical": practical,
            "oracle": threshold_dispatch(
                load,
                spec,
                feasible_threshold(load, spec, dt, billed=month_billed),
                dt,
                billed=month_billed,
            ),
        }
        if with_optimal:
            dispatches["optimal"] = optimal_dispatch(load, prices, rows, spec, dt)
        for name, dispatch in dispatches.items():
            record.update(_score(name, dispatch, bill, base))
        records.append(record)
    return pd.DataFrame(records).set_index("month")


@dataclass(frozen=True)
class Bill:
    """A month's bill split into the parts M4 scales separately."""

    total: float
    demand: float
    energy: float


def _score(
    name: str, dispatch: Dispatch, bill: Callable[[np.ndarray], Bill], base: Bill
) -> dict[str, object]:
    net = dispatch.net_kw
    cost = bill(net)
    idle = cost.total > base.total + COST_TOL_USD
    kept = base if idle else cost
    return {
        f"{name}_peak_kw": float(dispatch.load_kw.max() if idle else net.max()),
        f"{name}_bill_usd": kept.total,
        f"{name}_demand_usd": kept.demand,
        f"{name}_energy_usd": kept.energy,
        f"{name}_discharged_kwh": 0.0 if idle else float(dispatch.discharge_kw.sum()),
        f"{name}_idle": bool(idle),
    }


def annual_summary(monthly: pd.DataFrame) -> dict[str, float]:
    """Annual bill savings per strategy and the practical controller's capture ratio."""
    base = float(monthly["base_bill_usd"].sum())
    out: dict[str, float] = {"base_bill_usd": base}
    for name in STRATEGIES[1:]:
        column = f"{name}_bill_usd"
        if column in monthly:
            out[f"{name}_savings_usd"] = base - float(monthly[column].sum())
            for part in ("demand", "energy"):
                out[f"{name}_{part}_savings_usd"] = float(
                    monthly[f"base_{part}_usd"].sum() - monthly[f"{name}_{part}_usd"].sum()
                )
            out[f"{name}_peak_reduction_kw_mean"] = float(
                (monthly["base_peak_kw"] - monthly[f"{name}_peak_kw"]).mean()
            )
    optimal = out.get("optimal_savings_usd")
    if optimal is not None:
        out["capture_ratio"] = out["practical_savings_usd"] / optimal if optimal > 0 else np.nan
    return out


def simulate_sites(
    sites: list[Site],
    loads: Mapping[str, pd.Series],
    tariffs: Mapping[str, Tariff],
    spec: BatterySpec,
    *,
    with_optimal: bool = True,
    history: History = "causal",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run `simulate_site` for each site. Returns (monthly rows, one summary row per site).

    `tariffs` maps site_id to the tariff already matched to it; matching (and failing loudly
    on zero or several matches) is the caller's job, see `data/tariffs.match_tariff`.
    """
    monthly_frames, summaries = [], []
    for site in sites:
        tariff = tariffs[site.site_id]
        monthly = simulate_site(
            loads[site.site_id], tariff, spec, with_optimal=with_optimal, history=history
        )
        tags = {"site_id": site.site_id, "tariff_id": tariff.tariff_id}
        monthly_frames.append(monthly.reset_index().assign(**tags))
        summaries.append(
            {
                **tags,
                "building_type": site.building_type,
                "peak_kw": site.peak_kw,
                "tariff_is_test_fixture": tariff.is_test_fixture,
                "tariff_is_proxy": tariff.is_proxy,
                **annual_summary(monthly),
            }
        )
    return pd.concat(monthly_frames, ignore_index=True), pd.DataFrame(summaries)
