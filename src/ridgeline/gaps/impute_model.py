"""Regression imputer: ridge least squares on calendar, weather and peer-site features.

Fit on the site's own observed intervals, predict the missing ones:

    kW_t ~ (weekday/weekend x 15-min slot dummies)
         + cooling/heating degree terms (plain and x occupancy)
         + peer signal (same-type sites' normalized load at t), optional

Plain numpy linear algebra, no ML dependency: the model is small, fast and every coefficient
can be printed and explained.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from ridgeline.gaps.features import (
    degree_features,
    occupied_hours,
    slot_daytype_dummies,
)


class RegressionSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    cooling_base_c: float
    heating_base_c: float
    ridge_lambda: float = Field(ge=0)


def design_matrix(
    index: pd.DatetimeIndex,
    temp_c: np.ndarray,
    peer: np.ndarray | None,
    spec: RegressionSpec,
) -> np.ndarray:
    """Feature matrix, one row per interval. Columns: 192 dummies, 4 degree terms, [peer]."""
    blocks = [
        slot_daytype_dummies(index),
        degree_features(temp_c, occupied_hours(index), spec.cooling_base_c, spec.heating_base_c),
    ]
    if peer is not None:
        blocks.append(peer.reshape(-1, 1))
    return np.hstack(blocks)


def ridge_fit(x: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    """Solve (X'X + lam I) b = X'y."""
    gram = x.T @ x + lam * np.eye(x.shape[1])
    return np.asarray(np.linalg.solve(gram, x.T @ y), dtype=float)


def regression_fill(
    series: pd.Series,
    temp_c: np.ndarray,
    peer: np.ndarray | None,
    spec: RegressionSpec,
) -> pd.Series:
    """Fill NaN intervals of `series` with model predictions (clipped at zero).

    `temp_c` and `peer` are aligned to `series.index` and must have no gaps of their own.
    """
    x = design_matrix(pd.DatetimeIndex(series.index), temp_c, peer, spec)
    return fill_from_design(series, x, spec.ridge_lambda)


def fill_from_design(series: pd.Series, x: np.ndarray, ridge_lambda: float) -> pd.Series:
    """`regression_fill` with a precomputed design matrix (reuse it across gaps of one site)."""
    if x.shape[0] != len(series):
        raise ValueError("design matrix rows must match the series length")
    missing = series.isna().to_numpy()
    if not missing.any():
        return series.copy()
    if missing.all():
        raise ValueError("no observed data to fit on")
    beta = ridge_fit(x[~missing], series.to_numpy(dtype=float)[~missing], ridge_lambda)
    out = series.copy()
    out[missing] = np.maximum(x[missing] @ beta, 0.0)
    return out
