from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from ridgeline.gaps.evaluate import evaluate_gap, mae, mape, monthly_peak_errors
from ridgeline.gaps.inject import Gap
from tests.gaps_helpers import weekly_profile_series, year_index

GAP = Gap(start=datetime(2018, 3, 10, 5, tzinfo=UTC), end=datetime(2018, 4, 25, 4, tzinfo=UTC))


def test_mae_and_mape() -> None:
    actual = np.array([100.0, 200.0, 0.0])
    pred = np.array([110.0, 180.0, 5.0])
    assert mae(actual, pred) == pytest.approx(35 / 3)
    assert mape(actual, pred) == pytest.approx(10.0)  # zero-actual interval excluded


def test_monthly_peak_errors_only_cover_touched_months() -> None:
    actual = weekly_profile_series(year_index())
    filled = actual * 0.9
    table = monthly_peak_errors(actual, filled, GAP)
    assert [str(m) for m in table["month"]] == ["2018-03", "2018-04"]
    np.testing.assert_allclose(table["peak_error_pct"], -10.0)
    assert 0 < table["gap_fraction"].iloc[0] < 1


def test_monthly_peak_uses_local_calendar_month() -> None:
    """Regression guard: 2018-04-01 02:00 UTC is still March 31 in Boston."""
    index = pd.DatetimeIndex(["2018-04-01 02:00", "2018-04-01 06:00"], tz="UTC")
    actual = pd.Series([500.0, 100.0], index=index)
    gap = Gap(start=index[0].to_pydatetime(), end=datetime(2018, 4, 2, tzinfo=UTC))
    table = monthly_peak_errors(actual, actual, gap)
    assert dict(zip(table["month"].astype(str), table["actual_peak_kw"], strict=True)) == {
        "2018-03": 500.0,
        "2018-04": 100.0,
    }


def test_evaluate_gap_scores_each_imputer() -> None:
    actual = weekly_profile_series(year_index())
    perfect = lambda s: s.fillna(actual)  # noqa: E731
    halved = lambda s: s.fillna(actual * 0.5)  # noqa: E731
    records, peaks = evaluate_gap(actual, GAP, {"perfect": perfect, "halved": halved})
    by_name = {r["method"]: r for r in records}
    assert by_name["perfect"]["mae_kw"] == 0.0
    assert by_name["halved"]["mape_pct"] == pytest.approx(50.0)
    assert set(pd.concat(peaks)["method"]) == {"perfect", "halved"}


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (lambda s: s, "left missing values"),
        (lambda s: (s * 2).fillna(1.0), "modified observed data"),
    ],
)
def test_evaluate_gap_rejects_misbehaving_imputers(bad, message) -> None:
    actual = weekly_profile_series(year_index())
    with pytest.raises(ValueError, match=message):
        evaluate_gap(actual, GAP, {"bad": bad})
