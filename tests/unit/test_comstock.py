from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd
import pytest

from ridgeline.config import SiteSelectionConfig, load_settings
from ridgeline.data import comstock
from ridgeline.data.comstock import (
    INTERVALS_PER_YEAR,
    TOTAL_KWH_COL,
    check_full_year,
    combine_metadata,
    normalize_timeseries,
    screen_candidates,
    select_sites,
    slim_metadata,
)
from tests.conftest import TYPES, make_slim_metadata

# --- URLs -------------------------------------------------------------------------------


def test_urls_follow_oedi_layout() -> None:
    cfg = load_settings().comstock
    assert comstock.timeseries_url(cfg, 123).endswith("upgrade=0/state=MA/123-0.parquet")
    assert comstock.metadata_url(cfg, "G2500170").endswith(
        "state=MA/county=G2500170/MA_G2500170_baseline.parquet"
    )
    assert comstock.weather_url(cfg, "G2500170").endswith("weather/amy2018/G2500170_2018.csv")


# --- metadata ---------------------------------------------------------------------------


def _raw_meta_rows() -> pd.DataFrame:
    base = {
        "in.comstock_building_type": "MediumOffice",
        "in.nhgis_county_gisjoin": "G2500170",
        "in.nhgis_puma_gisjoin": "G25000503",
        "in.county_name": "MA, Middlesex County",
        "in.sqft..ft2": 50000.0,
        "out.utility_bills.electricity_utility_eia_id": "11804",
        "out.electricity.total.peak_demand..kw": 300.0,
        "out.electricity.total.energy_consumption..kwh": 876000.0,
        "in.as_simulated_state_name": "Massachusetts",
    }
    rows = [
        # Building 1 appears in two tracts (allocation rows); weight decides which is kept.
        {**base, "bldg_id": 1, "weight": 0.5, "in.nhgis_tract_gisjoin": "T-A"},
        {**base, "bldg_id": 1, "weight": 2.0, "in.nhgis_tract_gisjoin": "T-B"},
        # Building 2 was simulated in Connecticut and must be dropped.
        {**base, "bldg_id": 2, "weight": 1.0, "in.nhgis_tract_gisjoin": "T-C"}
        | {"in.as_simulated_state_name": "Connecticut"},
        {**base, "bldg_id": 3, "weight": 1.0, "in.nhgis_tract_gisjoin": "T-D"}
        | {"out.utility_bills.electricity_utility_eia_id": None},
    ]
    return pd.DataFrame(rows)


def test_slim_metadata_dedupes_allocations_keeping_max_weight() -> None:
    """Regression (M0): raw metadata has one row per building x tract allocation."""
    slim = slim_metadata(_raw_meta_rows())
    assert slim["bldg_id"].is_unique
    assert slim.set_index("bldg_id").loc[1, "tract_gisjoin"] == "T-B"


def test_slim_metadata_drops_buildings_simulated_outside_massachusetts() -> None:
    """Regression (M0): about a third of MA rows were simulated in Connecticut."""
    assert 2 not in set(slim_metadata(_raw_meta_rows())["bldg_id"])


def test_slim_metadata_parses_utility_and_mean_kw() -> None:
    slim = slim_metadata(_raw_meta_rows()).set_index("bldg_id")
    assert slim.loc[1, "utility_eiaid"] == 11804
    assert slim["utility_eiaid"].isna().loc[3]
    assert slim.loc[1, "mean_kw"] == pytest.approx(100.0)


def test_combine_metadata_keeps_one_row_per_building() -> None:
    a = make_slim_metadata(n_per_type=3)
    b = a.assign(weight=5.0, county_gisjoin="G2500270")
    combined = combine_metadata([a, b])
    assert combined["bldg_id"].is_unique
    assert set(combined["county_gisjoin"]) == {"G2500270"}


# --- screening and selection ------------------------------------------------------------


def test_screen_filters_peak_type_and_utility(selection_cfg: SiteSelectionConfig) -> None:
    meta = make_slim_metadata()
    meta.loc[0, "peak_kw"] = 50.0
    meta.loc[1, "building_type"] = "LargeHotel"
    meta.loc[2, "utility_eiaid"] = 1234
    screened = screen_candidates(meta, selection_cfg)
    assert not {1, 2, 3} & set(screened["bldg_id"])
    assert set(screened["par_tier"]) == {"low", "mid", "high"}


def test_par_tiers_are_ordered_within_each_type(selection_cfg: SiteSelectionConfig) -> None:
    screened = screen_candidates(make_slim_metadata(), selection_cfg)
    for _, group in screened.groupby("building_type"):
        means = group.groupby("par_tier")["par"].max()
        assert means["low"] < means["mid"] < means["high"]


def test_selection_is_deterministic_for_a_seed(selection_cfg: SiteSelectionConfig) -> None:
    meta = make_slim_metadata()
    assert select_sites(meta, selection_cfg) == select_sites(meta, selection_cfg)


def test_selection_changes_with_seed(selection_cfg: SiteSelectionConfig) -> None:
    meta = make_slim_metadata()
    other = selection_cfg.model_copy(update={"seed": selection_cfg.seed + 1})
    ids = [s.bldg_id for s in select_sites(meta, selection_cfg)]
    assert ids != [s.bldg_id for s in select_sites(meta, other)]


def test_selection_meets_type_and_tier_quotas(selection_cfg: SiteSelectionConfig) -> None:
    sites = select_sites(make_slim_metadata(), selection_cfg)
    q = selection_cfg.par_tier_quota
    assert len(sites) == selection_cfg.n_sites
    assert len({s.bldg_id for s in sites}) == len(sites)
    for btype in TYPES:
        tiers = Counter(s.par_tier for s in sites if s.building_type == btype)
        assert tiers == Counter({"low": q.low, "mid": q.mid, "high": q.high})


def test_dev_subset_spans_types_and_tiers(selection_cfg: SiteSelectionConfig) -> None:
    sites = select_sites(make_slim_metadata(), selection_cfg)
    dev = [s for s in sites if s.dev_subset]
    assert len(dev) == selection_cfg.dev_subset_size
    assert {s.building_type for s in dev} == set(TYPES)
    assert len({s.par_tier for s in dev}) >= 2


def test_selection_raises_when_a_stratum_is_too_small(
    selection_cfg: SiteSelectionConfig,
) -> None:
    with pytest.raises(ValueError, match="candidates in PAR tier"):
        select_sites(make_slim_metadata(n_per_type=4), selection_cfg)


# --- timeseries -------------------------------------------------------------------------


def _raw_year(kwh: float = 25.0) -> pd.DataFrame:
    stamps = pd.date_range("2018-01-01 00:15", periods=INTERVALS_PER_YEAR, freq="15min")
    return pd.DataFrame({"timestamp": stamps, TOTAL_KWH_COL: kwh})


def test_normalize_converts_kwh_per_interval_to_kw() -> None:
    series = normalize_timeseries(_raw_year(kwh=25.0))
    assert np.allclose(series.to_numpy(), 100.0)
    assert str(pd.DatetimeIndex(series.index).tz) == "UTC"
    assert series.index[0] == pd.Timestamp("2018-01-01 05:00", tz="UTC")


def test_normalize_rejects_partial_year() -> None:
    with pytest.raises(ValueError, match="intervals"):
        normalize_timeseries(_raw_year().iloc[:-1])


@pytest.mark.parametrize("bad", [np.nan, -1.0])
def test_check_full_year_rejects_missing_or_negative(bad: float) -> None:
    series = normalize_timeseries(_raw_year())
    series.iloc[100] = bad
    with pytest.raises(ValueError, match="missing or negative"):
        check_full_year(series)


def test_replacement_swaps_only_the_named_utility(selection_cfg: SiteSelectionConfig) -> None:
    """ADR-010: dropping a utility must leave every other selected site untouched."""
    meta = make_slim_metadata()
    # The default config already replaces 54913, so build the "before" case explicitly.
    no_swap = selection_cfg.model_copy(update={"replace_utility_eiaids": []})
    before = select_sites(meta, no_swap)
    assert any(s.utility_eiaid == 54913 for s in before)  # the test is not vacuous
    cfg = no_swap.model_copy(update={"replace_utility_eiaids": [54913]})
    after = select_sites(meta, cfg)
    assert len(after) == len(before)
    assert all(s.utility_eiaid != 54913 for s in after)
    assert len({s.bldg_id for s in after}) == len(after)
    for old, new in zip(before, after, strict=True):
        if old.utility_eiaid == 54913:
            assert (new.building_type, new.par_tier) == (old.building_type, old.par_tier)
        else:
            assert new == old
    assert [s.dev_subset for s in after] == [s.dev_subset for s in before]
    assert select_sites(meta, cfg) == after  # deterministic
