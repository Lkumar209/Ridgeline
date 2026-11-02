"""Score imputers by masking known data: interval accuracy and, more importantly, billing peaks.

Demand charges are set by each month's single highest interval, so an imputer can have a good
MAE and still be useless for peak shaving if it smooths peaks away. Both are reported.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np
import pandas as pd

from ridgeline.data.schemas import LOCAL_TZ
from ridgeline.gaps.inject import Gap, apply_gap, gap_mask

Imputer = Callable[[pd.Series], pd.Series]


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean absolute percentage error over intervals with non-zero actual load."""
    nonzero = actual != 0
    if not nonzero.any():
        return float("nan")
    return float(np.mean(np.abs((actual - predicted)[nonzero] / actual[nonzero])) * 100)


def local_month(index: pd.DatetimeIndex) -> pd.PeriodIndex:
    """Calendar month in local time, used as a stand-in for the billing cycle."""
    return index.tz_convert(LOCAL_TZ).tz_localize(None).to_period("M")


def monthly_peak_errors(actual: pd.Series, filled: pd.Series, gap: Gap) -> pd.DataFrame:
    """Per month touched by the gap: true vs. imputed billing peak (max kW over the month).

    `gap_fraction` is the share of the month's intervals inside the gap; when it is small the
    true peak usually falls outside the gap and the error is diluted.
    """
    index = pd.DatetimeIndex(actual.index)
    months = local_month(index)
    in_gap = gap_mask(index, gap)
    frame = pd.DataFrame(
        {"month": months, "actual": actual.to_numpy(), "filled": filled.to_numpy(), "gap": in_gap}
    )
    touched = frame.loc[frame["gap"], "month"].unique()
    grouped = frame[frame["month"].isin(touched)].groupby("month")
    out = grouped.agg(
        actual_peak_kw=("actual", "max"),
        filled_peak_kw=("filled", "max"),
        gap_fraction=("gap", "mean"),
    )
    out["peak_error_kw"] = out["filled_peak_kw"] - out["actual_peak_kw"]
    out["peak_error_pct"] = 100 * out["peak_error_kw"] / out["actual_peak_kw"]
    return out.reset_index()


def evaluate_gap(
    actual: pd.Series, gap: Gap, imputers: Mapping[str, Imputer]
) -> tuple[list[dict[str, object]], list[pd.DataFrame]]:
    """Mask `gap` in `actual`, run each imputer, and score it.

    Returns interval-metric records (one per imputer) and monthly peak tables (one per imputer,
    with a `method` column).
    """
    masked = apply_gap(actual, gap)
    in_gap = gap_mask(pd.DatetimeIndex(actual.index), gap)
    truth = actual.to_numpy()[in_gap]
    records: list[dict[str, object]] = []
    peaks: list[pd.DataFrame] = []
    for name, impute in imputers.items():
        filled = impute(masked)
        _check_fill(actual, masked, filled)
        pred = filled.to_numpy()[in_gap]
        records.append(
            {
                "method": name,
                "gap_start": gap.start,
                "gap_days": gap.duration.days,
                "mae_kw": mae(truth, pred),
                "mape_pct": mape(truth, pred),
                "mean_kw": float(truth.mean()),
            }
        )
        peaks.append(monthly_peak_errors(actual, filled, gap).assign(method=name))
    return records, peaks


def _check_fill(actual: pd.Series, masked: pd.Series, filled: pd.Series) -> None:
    """An imputer must fill every gap interval and leave observed data untouched."""
    if not filled.index.equals(actual.index):
        raise ValueError("imputer changed the index")
    if filled.isna().any():
        raise ValueError("imputer left missing values")
    observed = masked.notna().to_numpy()
    if not np.array_equal(filled.to_numpy()[observed], actual.to_numpy()[observed]):
        raise ValueError("imputer modified observed data")
