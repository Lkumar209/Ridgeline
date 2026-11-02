from __future__ import annotations

import numpy as np
import pandas as pd

from ridgeline.config import load_settings
from ridgeline.data.schemas import Site
from ridgeline.gaps.experiment import (
    BASELINE,
    REGRESSION,
    REGRESSION_PEERS,
    run_experiment,
    summarize,
)
from tests.gaps_helpers import synthetic_weather, weekly_profile_series, year_index

CFG = load_settings().gaps.model_copy(update={"gaps_per_site": 2})


def _site(i: int, btype: str) -> Site:
    return Site(
        site_id=f"cs-{i}",
        bldg_id=i,
        building_type=btype,
        county_gisjoin="G2500170",
        county_name="MA, Middlesex County",
        tract_gisjoin="T",
        utility_eiaid=11804,
        sqft=1000.0,
        peak_kw=200.0,
        mean_kw=60.0,
        par_tier="mid",
        dev_subset=i == 1,
    )


def _inputs() -> tuple[list[Site], dict[str, pd.Series], dict[str, pd.DataFrame]]:
    sites = [_site(1, "MediumOffice"), _site(2, "MediumOffice"), _site(3, "Warehouse")]
    base = weekly_profile_series(year_index())
    loads = {s.site_id: base * (1 + 0.1 * s.bldg_id) for s in sites}
    return sites, loads, {"G2500170": synthetic_weather()}


def test_experiment_is_reproducible_and_complete() -> None:
    sites, loads, weather = _inputs()
    m1, p1 = run_experiment(sites, loads, weather, CFG)
    m2, p2 = run_experiment(sites, loads, weather, CFG)
    pd.testing.assert_frame_equal(m1, m2)
    pd.testing.assert_frame_equal(p1, p2)
    assert len(m1) == 2 * (3 + 3 + 2)  # warehouse has no peer, so no peer method
    assert set(summarize(m1, p1).index) == {BASELINE, REGRESSION, REGRESSION_PEERS}


def test_scoring_a_subset_still_uses_unscored_sites_as_peers() -> None:
    """Regression: peers were drawn only from the scored subset, dropping the peer method."""
    sites, loads, weather = _inputs()
    metrics, _ = run_experiment(sites, loads, weather, CFG, score_ids={"cs-1"})
    assert set(metrics["site_id"]) == {"cs-1"}
    assert REGRESSION_PEERS in set(metrics["method"])


def test_perfectly_periodic_loads_are_recovered_by_baseline() -> None:
    sites, loads, weather = _inputs()
    metrics, _ = run_experiment(sites, loads, weather, CFG)
    assert np.allclose(metrics.loc[metrics["method"] == BASELINE, "mae_kw"], 0.0, atol=1e-9)
