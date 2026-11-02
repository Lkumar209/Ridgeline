from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from ridgeline.gaps.features import (
    degree_features,
    peer_signal,
    slot_daytype_dummies,
    temperature_on_index,
)
from ridgeline.gaps.impute_baseline import seasonal_profile_fill
from ridgeline.gaps.impute_model import (
    RegressionSpec,
    design_matrix,
    fill_from_design,
    regression_fill,
    ridge_fit,
)
from ridgeline.gaps.inject import Gap, apply_gap, gap_mask
from tests.gaps_helpers import synthetic_weather, weekly_profile_series, year_index

SPEC = RegressionSpec(cooling_base_c=18.0, heating_base_c=10.0, ridge_lambda=1e-6)
SUMMER = Gap(start=datetime(2018, 6, 15, 4, tzinfo=UTC), end=datetime(2018, 8, 15, 4, tzinfo=UTC))


def _weather_driven(index: pd.DatetimeIndex, temp: np.ndarray) -> pd.Series:
    base = weekly_profile_series(index)
    return base + 6.0 * np.maximum(temp - 18.0, 0.0)


# --- features ---------------------------------------------------------------------------


def test_dummies_are_one_hot() -> None:
    d = slot_daytype_dummies(year_index()[:500])
    assert d.shape == (500, 192)
    assert np.all(d.sum(axis=1) == 1)


def test_dummies_use_local_wall_clock_slot() -> None:
    # 2018-07-02 13:15 UTC is 09:15 EDT on a Monday: weekday slot 37. Saturday adds 96.
    index = pd.DatetimeIndex(["2018-07-02 13:15", "2018-07-07 13:15"], tz="UTC")
    assert list(slot_daytype_dummies(index).argmax(axis=1)) == [37, 96 + 37]


def test_degree_features() -> None:
    temp = np.array([5.0, 15.0, 25.0])
    occ = np.array([True, False, True])
    out = degree_features(temp, occ, cooling_base_c=18.0, heating_base_c=10.0)
    np.testing.assert_allclose(out[:, 0], [0, 0, 7])
    np.testing.assert_allclose(out[:, 1], [5, 0, 0])
    np.testing.assert_allclose(out[:, 2], [0, 0, 7])
    np.testing.assert_allclose(out[:, 3], [5, 0, 0])


def test_temperature_is_carried_forward_within_the_hour() -> None:
    weather = synthetic_weather()
    index = year_index()[:8]
    temp = temperature_on_index(weather, index)
    assert np.all(temp[:4] == weather["temp_c"].iloc[0])
    assert np.all(temp[4:] == weather["temp_c"].iloc[1])


def test_temperature_outside_weather_coverage_raises() -> None:
    early = pd.date_range("2017-12-31", periods=4, freq="15min", tz="UTC")
    with pytest.raises(ValueError, match="does not cover"):
        temperature_on_index(synthetic_weather(), early)


def test_peer_signal_normalizes_each_peer() -> None:
    index = year_index()[:10]
    a = pd.Series(np.full(10, 100.0), index=index)
    b = pd.Series(np.full(10, 5.0), index=index)
    np.testing.assert_allclose(peer_signal([a, b], index), 1.0)


def test_peer_signal_with_missing_peer_data_raises() -> None:
    index = year_index()[:10]
    with pytest.raises(ValueError, match="do not cover"):
        peer_signal([pd.Series(np.ones(5), index=index[:5])], index)


# --- baseline ---------------------------------------------------------------------------


def test_baseline_recovers_a_purely_weekly_pattern() -> None:
    truth = weekly_profile_series(year_index())
    filled = seasonal_profile_fill(apply_gap(truth, SUMMER), window_days=28)
    np.testing.assert_allclose(filled.to_numpy(), truth.to_numpy(), atol=1e-9)


def test_baseline_misses_weather_driven_summer_load() -> None:
    """Documents the baseline's known weakness, which the regression exists to fix."""
    index = year_index()
    temp = temperature_on_index(synthetic_weather(), index)
    truth = _weather_driven(index, temp)
    filled = seasonal_profile_fill(apply_gap(truth, SUMMER), window_days=28)
    window = gap_mask(index, SUMMER)
    assert filled[window].max() < 0.9 * truth[window].max()


def test_baseline_without_nearby_data_raises() -> None:
    truth = weekly_profile_series(year_index())
    masked = truth.copy()
    masked.iloc[:] = np.nan
    with pytest.raises(ValueError, match="no observed data"):
        seasonal_profile_fill(masked, window_days=28)


# --- regression -------------------------------------------------------------------------


def test_ridge_fit_recovers_exact_coefficients() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=(200, 3))
    beta = np.array([1.0, -2.0, 0.5])
    np.testing.assert_allclose(ridge_fit(x, x @ beta, lam=0.0), beta, atol=1e-10)


def test_regression_recovers_weather_driven_summer_load() -> None:
    index = year_index()
    temp = temperature_on_index(synthetic_weather(), index)
    truth = _weather_driven(index, temp)
    filled = regression_fill(apply_gap(truth, SUMMER), temp, None, SPEC)
    window = gap_mask(index, SUMMER)
    error = np.abs(filled[window] - truth[window])
    assert error.mean() < 0.01 * truth[window].mean()
    assert filled[window].max() == pytest.approx(truth[window].max(), rel=0.01)


def test_regression_uses_peer_signal() -> None:
    """A load that tracks its peers exactly is recovered once the peer column is added."""
    index = year_index()
    temp = temperature_on_index(synthetic_weather(), index)
    rng = np.random.default_rng(5)
    shock = pd.Series(rng.normal(1.0, 0.2, len(index)).clip(0.2), index=index)
    truth = 80.0 * shock
    peer = peer_signal([shock * 3.0], index)
    masked = apply_gap(truth, SUMMER)
    window = gap_mask(index, SUMMER)
    without = regression_fill(masked, temp, None, SPEC)[window]
    with_peer = regression_fill(masked, temp, peer, SPEC)[window]
    assert np.abs(with_peer - truth[window]).mean() < 0.1 * np.abs(without - truth[window]).mean()


def test_regression_without_gaps_returns_copy() -> None:
    truth = weekly_profile_series(year_index())
    temp = temperature_on_index(synthetic_weather(), pd.DatetimeIndex(truth.index))
    out = regression_fill(truth, temp, None, SPEC)
    assert out.equals(truth) and out is not truth


def test_regression_predictions_are_clipped_at_zero() -> None:
    index = year_index()
    temp = temperature_on_index(synthetic_weather(), index)
    truth = pd.Series(np.where(temp > 18, 0.0, 50.0), index=index)
    filled = regression_fill(apply_gap(truth, SUMMER), temp, None, SPEC)
    assert (filled >= 0).all()


def test_gap_length_is_whole_days() -> None:
    assert SUMMER.duration == timedelta(days=61)


def test_precomputed_design_matches_regression_fill() -> None:
    index = year_index()
    temp = temperature_on_index(synthetic_weather(), index)
    masked = apply_gap(_weather_driven(index, temp), SUMMER)
    x = design_matrix(index, temp, None, SPEC)
    pd.testing.assert_series_equal(
        fill_from_design(masked, x, SPEC.ridge_lambda), regression_fill(masked, temp, None, SPEC)
    )
    with pytest.raises(ValueError, match="rows must match"):
        fill_from_design(masked, x[:-1], SPEC.ridge_lambda)
