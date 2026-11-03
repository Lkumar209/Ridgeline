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
        "other_revenue",
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


def test_required_other_revenue_closes_the_central_gap() -> None:
    """Adding exactly the required revenue makes the central-case NPV zero (or keeps it >= 0)."""
    from ridgeline.ranking.pipeline import required_other_revenue
    from ridgeline.scenarios.cashflow import annuity_factor
    from ridgeline.scenarios.montecarlo import central_draws, expected_npv

    sites, i = five_sites(), inputs()
    need = required_other_revenue(sites, i)["required_other_revenue_usd_per_kw_year"].to_numpy()
    center = central_draws(i)
    npv = expected_npv(sites, i, center)[:, 0]
    factor = annuity_factor(center.discount_rate, i.life_years)[0]
    np.testing.assert_allclose(np.minimum(npv, 0) + need * i.power_kw * factor, 0, atol=1e-6)
    assert (need >= 0).all()


def test_revenue_sweep_is_monotone() -> None:
    result = rank_sites(five_sites(), inputs(), n_draws=300, seed=4)
    sweep = result.revenue_sweep
    assert sweep["sites_likely_viable"].is_monotonic_increasing
    assert sweep["sites_robustly_viable"].is_monotonic_increasing
    assert (sweep["sites_robustly_viable"] <= sweep["sites_likely_viable"]).all()


def test_annuity_factor_matches_closed_form() -> None:
    from ridgeline.scenarios.cashflow import annuity_factor

    r = np.array([0.05])
    expected = (1 - 1.05**-15) / 0.05
    assert annuity_factor(r, 15)[0] == pytest.approx(expected)


def test_fan_final_year_equals_npv_percentiles() -> None:
    """The fan chart and the ranking come from the same draws and the same cash-flow formula."""
    result = rank_sites(five_sites(), inputs(), n_draws=500, seed=9)
    last = result.fan[result.fan["year"] == result.fan["year"].max()].set_index("site_id")
    table = result.ranking.set_index("site_id")
    for col, pct in (("p10", "npv_p10"), ("p50", "npv_p50"), ("p90", "npv_p90")):
        np.testing.assert_allclose(last[col], table.loc[last.index, pct], rtol=1e-9)
    first = result.fan[result.fan["year"] == 0]
    assert (first["p50"] < 0).all()  # year 0 is the upfront cost
    assert (
        (result.fan["p10"] <= result.fan["p50"]) & (result.fan["p50"] <= result.fan["p90"])
    ).all()


# --- wording: breakeven label and headline (regression: negative $/kW confused readers) ---


def test_breakeven_label_says_never_pays_back_at_or_below_zero() -> None:
    from ridgeline.ranking.pipeline import NEVER_PAYS_BACK, breakeven_label

    assert NEVER_PAYS_BACK == "never pays back, even at $0 battery cost"
    assert breakeven_label(-27.0) == NEVER_PAYS_BACK
    assert breakeven_label(0.0) == NEVER_PAYS_BACK
    assert breakeven_label(56.14) == "$56/kW"


def _ranking(rows: list[tuple[str, int, int, float]]) -> pd.DataFrame:
    """(site_id, rank, rank_by_p50, breakeven $/kW) -> a minimal ranking table."""
    return pd.DataFrame(
        [
            {
                "site_id": s,
                "rank": r,
                "rank_by_p50": r50,
                "breakeven_capex_usd_per_kw": b,
                "npv_p90": -100_000.0,
                "p_npv_positive": 0.0,
            }
            for s, r, r50, b in rows
        ]
    )


def test_headline_names_the_closest_site_when_it_is_not_the_most_robust() -> None:
    from ridgeline.ranking.pipeline import headline_sentence

    table = _ranking([("cs-a", 1, 2, -27.0), ("cs-b", 6, 1, 56.0), ("cs-c", 2, 3, -80.0)])
    text = headline_sentence(table, inputs(), 8000)
    assert "most robust site (cs-a, ranked 1st by bad-case P10 NPV)" in text
    assert "closest to breaking even is a different one, cs-b" in text
    assert "best by median NPV but ranked 6th on robustness" in text
    assert "about $56/kW" in text
    assert "the best site" not in text  # the ambiguous phrase is gone


def test_headline_when_the_most_robust_site_is_also_closest() -> None:
    from ridgeline.ranking.pipeline import headline_sentence

    text = headline_sentence(_ranking([("cs-a", 1, 1, 40.0), ("cs-b", 2, 2, 10.0)]), inputs(), 100)
    assert "In the central case it breaks even only if the battery cost about $40/kW" in text
    assert "different one" not in text


def test_headline_when_no_site_ever_breaks_even() -> None:
    from ridgeline.ranking.pipeline import headline_sentence

    text = headline_sentence(_ranking([("cs-a", 1, 1, -5.0), ("cs-b", 2, 2, -9.0)]), inputs(), 100)
    assert "every site never pays back, even at $0 battery cost" in text
    assert "/kW, versus" not in text


def test_revenue_sentence_names_the_site_it_means() -> None:
    result = rank_sites(five_sites(), inputs(), n_draws=300, seed=2)
    text = result.explanations["other_revenue"]
    need = result.ranking.set_index("site_id")["required_other_revenue_usd_per_kw_year"]
    assert f"the site needing the least ({need.idxmin()}, ranked" in text
    assert "the best site" not in text
