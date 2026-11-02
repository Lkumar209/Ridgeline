from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ridgeline.ranking.metrics import summarize_npv
from ridgeline.ranking.pipeline import rank_sites, usd
from ridgeline.ranking.sensitivity import compare_ranks, neighbour_gap, tornado, verdict
from tests.scenario_helpers import five_sites, inputs, site


def test_summary_ranks_by_p10_not_mean() -> None:
    """A steady site beats a volatile one with a higher average: that is the point."""
    sites = [site(1, 1.0), site(2, 1.0)]
    steady = np.full(100, 50.0)
    volatile = np.concatenate([np.full(20, -100.0), np.full(80, 200.0)])  # mean 140, P10 -100
    table = summarize_npv(np.vstack([steady, volatile]), sites).set_index("site_id")
    assert table.loc["s1", "rank"] == 1 and table.loc["s2", "rank"] == 2
    assert table.loc["s2", "rank_by_p50"] == 1
    assert table.loc["s1", "p_npv_positive"] == 1.0
    assert table.loc["s2", "p_npv_positive"] == pytest.approx(0.8)


def test_compare_ranks_counts_moves_and_top_k() -> None:
    base = pd.Series({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5})
    other = pd.Series({"a": 4, "b": 2, "c": 3, "d": 1, "e": 5})
    shift = compare_ranks(base, other, "x", "Changing x", k=2)
    assert (shift.moved, shift.max_move, shift.top_kept) == (2, 3, 1)
    assert shift.sentence.startswith("Changing x: the order changes substantially. 2 of 5 sites")


def test_verdict_words_follow_the_count() -> None:
    assert verdict(0, 40) == "the order barely changes"
    assert verdict(8, 40) == "only a few sites change places"
    assert verdict(9, 40) == "the order changes substantially"


def test_cost_inputs_never_reorder_sites() -> None:
    """Every site carries the same battery, so capex, incentive and O&M shift all NPVs equally."""
    rows = tornado(five_sites(), inputs()).set_index("input").to_dict(orient="index")
    for name in ("capex_usd_per_kw", "incentive", "om_usd_per_kw_year"):
        assert rows[name]["max_move"] == 0
        assert rows[name]["npv_swing_usd"] > 0


def test_rank_sites_gives_every_explanation() -> None:
    result = rank_sites(five_sites(), inputs(), n_draws=300, seed=11)
    assert set(result.explanations) == {
        "headline",
        "closeness",
        "rank_stability",
        "proxy_tariff",
        "all_demand",
        "tenant_churn",
    }
    assert list(result.ranking["rank"]) == [1, 2, 3, 4, 5]
    assert "breakeven_capex_usd_per_kw" in result.ranking
    assert neighbour_gap(result.ranking) >= 0
    assert "$-" not in " ".join(result.explanations.values())  # money reads "-$1,234"


def test_usd_formatting() -> None:
    assert usd(-130785.2) == "-$130,785"
    assert usd(56.4) == "$56"
