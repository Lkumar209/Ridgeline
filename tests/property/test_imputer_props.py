"""Properties every imputer must satisfy, on random gaps over a weather-driven series."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from hypothesis import given, settings
from hypothesis import strategies as st

from ridgeline.gaps.features import temperature_on_index
from ridgeline.gaps.impute_baseline import seasonal_profile_fill
from ridgeline.gaps.impute_model import RegressionSpec, regression_fill
from ridgeline.gaps.inject import Gap, apply_gap
from tests.gaps_helpers import synthetic_weather, weekly_profile_series, year_index

INDEX = year_index()
TEMP = temperature_on_index(synthetic_weather(), INDEX)
TRUTH = weekly_profile_series(INDEX) + 5.0 * np.maximum(TEMP - 18.0, 0.0)
SPEC = RegressionSpec(cooling_base_c=18.0, heating_base_c=10.0, ridge_lambda=1.0)

gaps = st.tuples(st.integers(min_value=0, max_value=len(INDEX) - 96 * 92), st.integers(1, 92)).map(
    lambda t: Gap(
        start=INDEX[t[0]].to_pydatetime(),
        end=(INDEX[t[0]] + timedelta(days=t[1])).to_pydatetime(),
    )
)


def _imputers() -> dict[str, object]:
    return {
        "baseline": lambda s: seasonal_profile_fill(s, window_days=28),
        "regression": lambda s: regression_fill(s, TEMP, None, SPEC),
    }


@settings(max_examples=25, deadline=None)
@given(gap=gaps)
def test_imputers_fill_gap_only_and_stay_non_negative(gap: Gap) -> None:
    masked = apply_gap(TRUTH, gap)
    observed = masked.notna().to_numpy()
    for impute in _imputers().values():
        filled: pd.Series = impute(masked)  # type: ignore[operator]
        assert not filled.isna().any()
        assert (filled >= 0).all()
        np.testing.assert_array_equal(filled.to_numpy()[observed], TRUTH.to_numpy()[observed])
