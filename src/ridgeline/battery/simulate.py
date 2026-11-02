"""Simulate one site for one year, month by month, under several dispatch strategies.

Each billing month is simulated independently, with the battery starting full (DECISIONS.md
ADR-008). Strategies:

* ``base``: no battery.
* ``practical``: the threshold controller. Its starting threshold is the lowest threshold
  the battery could have held over the *previous* month (persistence: history only, no
  foresight), and it ratchets up when breached. January uses December of the same data year,
  because we have a single weather year.
* ``oracle``: the same controller with the lowest feasible threshold for the month itself.
  This is a diagnostic: it isolates the cost of not knowing the threshold.
* ``optimal``: the perfect-foresight LP (`battery/optimal.py`), an upper bound on savings.

An operator can always leave the battery idle. If a controller's month would cost more than
no battery (round-trip losses outweighing demand savings), that month is billed as idle and
flagged. So the bill with a battery is never above the bill without one, by construction.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from ridgeline.battery.billing import interval_prices, month_bill
from ridgeline.battery.dispatch import Dispatch, feasible_threshold, threshold_dispatch
from ridgeline.battery.optimal import optimal_dispatch
from ridgeline.data.schemas import BatterySpec, Tariff

STRATEGIES = ("base", "practical", "oracle", "optimal")
COST_TOL_USD = 1e-6


def simulate_site(
    load_kw: pd.Series, tariff: Tariff, spec: BatterySpec, *, with_optimal: bool = True
) -> pd.DataFrame:
    """One row per local month with peaks, bills and flags for each strategy."""
    index = pd.DatetimeIndex(load_kw.index)
    dt = (index[1] - index[0]).total_seconds() / 3600
    prices = interval_prices(index, tariff)
    values = load_kw.to_numpy(dtype=float)
    months = list(prices.month.unique())
    rows_by_month = [np.flatnonzero(prices.month == m) for m in months]

    records = []
    for i, (month, rows) in enumerate(zip(months, rows_by_month, strict=True)):
        load = values[rows]
        previous = values[rows_by_month[i - 1]]  # i = 0 wraps to December (single data year)

        def bill(net: np.ndarray, rows: np.ndarray = rows) -> float:
            full = np.zeros(len(values))
            full[rows] = net
            return month_bill(full, prices, rows, dt, tariff.fixed_monthly_usd)["total_usd"]

        start_threshold = feasible_threshold(previous, spec, dt)
        base_bill = bill(load)
        record: dict[str, object] = {
            "month": str(month),
            "practical_start_threshold_kw": start_threshold,
            "base_peak_kw": float(load.max()),
            "base_bill_usd": base_bill,
        }
        dispatches: dict[str, Dispatch] = {
            "practical": threshold_dispatch(load, spec, start_threshold, dt),
            "oracle": threshold_dispatch(load, spec, feasible_threshold(load, spec, dt), dt),
        }
        if with_optimal:
            dispatches["optimal"] = optimal_dispatch(load, prices, rows, spec, dt)
        for name, dispatch in dispatches.items():
            record.update(_score(name, dispatch, bill, base_bill))
        records.append(record)
    return pd.DataFrame(records).set_index("month")


def _score(
    name: str, dispatch: Dispatch, bill: Callable[[np.ndarray], float], base_bill: float
) -> dict[str, object]:
    net = dispatch.net_kw
    cost = bill(net)
    idle = cost > base_bill + COST_TOL_USD
    return {
        f"{name}_peak_kw": float(dispatch.load_kw.max() if idle else net.max()),
        f"{name}_bill_usd": base_bill if idle else cost,
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
            out[f"{name}_peak_reduction_kw_mean"] = float(
                (monthly["base_peak_kw"] - monthly[f"{name}_peak_kw"]).mean()
            )
    optimal = out.get("optimal_savings_usd")
    if optimal is not None:
        out["capture_ratio"] = out["practical_savings_usd"] / optimal if optimal > 0 else np.nan
    return out
