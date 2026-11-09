"""M4 end to end: simulated savings -> Monte Carlo -> robustness ranking -> sensitivity.

Everything here is deterministic given the seed. The scenario comparisons reuse the same
global draws and per-site randomness, so a rank change is caused by the one thing that changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ridgeline.assumptions import Assumption
from ridgeline.data.schemas import Site
from ridgeline.ranking.metrics import summarize_npv
from ridgeline.ranking.sensitivity import (
    RankShift,
    churn_sentence,
    compare_ranks,
    moves_word,
    neighbour_gap,
    tornado,
    verdict,
)
from ridgeline.scenarios.cashflow import Draws, annuity_factor
from ridgeline.scenarios.inputs import EconomicInputs, SiteEconomics, churn_hazard
from ridgeline.scenarios.montecarlo import (
    cashflow_fan,
    central_draws,
    expected_npv,
    run_monte_carlo,
    sample_draws,
    site_randomness,
)

PROXY_SWEEP = (0.7, 1.3)


@dataclass(frozen=True)
class RankingResult:
    ranking: pd.DataFrame
    tornado: pd.DataFrame
    revenue_sweep: pd.DataFrame
    fan: pd.DataFrame  # site_id, year, p10, p50, p90 of cumulative discounted cash flow
    shifts: list[RankShift] = field(default_factory=list)
    explanations: dict[str, str] = field(default_factory=dict)


def site_economics(
    sites: list[Site], savings: pd.DataFrame, assumptions: dict[str, Assumption]
) -> list[SiteEconomics]:
    """Join M3 practical-controller savings to sites and their churn hazards."""
    rows = savings.set_index("site_id").to_dict(orient="index")
    return [
        SiteEconomics(
            site_id=s.site_id,
            bldg_id=s.bldg_id,
            building_type=s.building_type,
            tariff_is_proxy=bool(rows[s.site_id]["tariff_is_proxy"]),
            tariff_id=str(rows[s.site_id]["tariff_id"]),
            demand_savings_usd=float(rows[s.site_id]["practical_demand_savings_usd"]),
            energy_savings_usd=float(rows[s.site_id]["practical_energy_savings_usd"]),
            churn_hazard=churn_hazard(assumptions, s.building_type),
        )
        for s in sites
    ]


def rank_sites(
    sites: list[SiteEconomics], inputs: EconomicInputs, n_draws: int, seed: int
) -> RankingResult:
    draws = sample_draws(inputs, n_draws, seed)
    randomness = site_randomness(sites, n_draws, inputs.life_years, inputs.savings_noise_sd, seed)

    def run(group: list[SiteEconomics], d: Draws = draws, churn: bool = True) -> pd.DataFrame:
        npv = run_monte_carlo(group, inputs, d, randomness, churn=churn)
        return summarize_npv(npv, group)

    base_npv = run_monte_carlo(sites, inputs, draws, randomness)
    fan = _fan_table(sites, cashflow_fan(sites, inputs, draws, randomness))
    base = summarize_npv(base_npv, sites)
    sweep = revenue_sweep(base_npv, draws, inputs)
    base_rank = _ranks(base)
    # Positions within the seed-to-seed noise are ties, so only bigger moves count as "moved".
    stability = _seed_stability(sites, inputs, n_draws, seed, base_rank)
    threshold = max(3, stability.max_move + 1)

    def shift(
        other: pd.DataFrame, label: str, change: str, base_rank: pd.Series = base_rank
    ) -> RankShift:
        return compare_ranks(base_rank, _ranks(other), label, change, threshold=threshold)

    n_proxy = sum(s.tariff_is_proxy for s in sites)
    # The proxy sweep only means something when some site is on a proxy tariff (none since ADR-016).
    proxy_shifts: list[RankShift] = []
    for value in PROXY_SWEEP if n_proxy else ():
        pinned = run(sites, draws.with_value("proxy_demand_multiplier", value))
        change = f"If the proxy demand charge ({n_proxy} sites above 200 kW) were {_pct(value)}"
        proxy_shifts.append(shift(pinned, f"proxy_demand_x{value:g}", change))
    demand_shifts: list[RankShift] = []
    everyone_proxy = [s.model_copy(update={"tariff_is_proxy": True}) for s in sites]
    for value in PROXY_SWEEP:
        everyone = run(everyone_proxy, draws.with_value("proxy_demand_multiplier", value))
        demand_shifts.append(
            shift(
                everyone,
                f"all_demand_x{value:g}",
                f"If every site's demand charge were {_pct(value)}",
            )
        )
    shifts = [*proxy_shifts, *demand_shifts]
    no_churn = run(sites, churn=False)
    churn_shift = compare_ranks(
        _ranks(no_churn), base_rank, "churn_on_vs_off", "Adding tenant churn", threshold=threshold
    )
    shifts.append(churn_shift)
    shifts.append(stability)
    base = base.merge(breakeven_capex(sites, inputs), on="site_id").merge(
        required_other_revenue(sites, inputs), on="site_id"
    )
    gap = neighbour_gap(base)
    explanations = {
        "headline": headline_sentence(base, inputs, n_draws),
        "other_revenue": _revenue_sentence(base, sweep),
        "closeness": (
            f"The sites are close together: neighbours in the ranking differ by a median "
            f"${gap:,.0f} of bad-case value, so small input changes can swap neighbours "
            "without changing the overall picture."
        ),
        "rank_stability": (
            f"Re-running with a different random seed moves no site more than "
            f"{stability.max_move} places, so treat sites within {stability.max_move} places of "
            f"each other as tied; below, a site only counts as moved if it shifts {threshold} or "
            "more places."
        ),
        "all_demand": _all_demand_sentence(demand_shifts),
        "tenant_churn": churn_sentence(base, no_churn, churn_shift),
    }
    if proxy_shifts:
        explanations["proxy_tariff"] = _proxy_sentence(proxy_shifts, n_proxy)
    return RankingResult(base, tornado(sites, inputs, threshold), sweep, fan, shifts, explanations)


def _fan_table(sites: list[SiteEconomics], fan: np.ndarray) -> pd.DataFrame:
    years = np.arange(fan.shape[2])
    frames = [
        pd.DataFrame({"site_id": s.site_id, "year": years, "p10": f[0], "p50": f[1], "p90": f[2]})
        for s, f in zip(sites, fan, strict=True)
    ]
    return pd.concat(frames, ignore_index=True)


def _seed_stability(
    sites: list[SiteEconomics],
    inputs: EconomicInputs,
    n_draws: int,
    seed: int,
    base_rank: pd.Series,
) -> RankShift:
    """How much the ranking moves from Monte Carlo sampling alone (a second seed)."""
    other = seed + 1
    draws = sample_draws(inputs, n_draws, other)
    rand = site_randomness(sites, n_draws, inputs.life_years, inputs.savings_noise_sd, other)
    rerun = summarize_npv(run_monte_carlo(sites, inputs, draws, rand), sites)
    return compare_ranks(base_rank, _ranks(rerun), "seed_stability", "Changing the random seed")


def breakeven_capex(sites: list[SiteEconomics], inputs: EconomicInputs) -> pd.DataFrame:
    """Capex ($/kW, 2025$) at which a site's central-case expected NPV is zero.

    Zero or negative means it never pays back, even at $0 battery cost (O&M exceeds savings);
    `breakeven_label` turns that into words for readers.
    """
    center = central_draws(inputs)
    present_value = expected_npv(sites, inputs, center.with_value("capex_usd_per_kw", 0.0))[:, 0]
    per_kw = present_value / (inputs.power_kw * (1 - inputs.incentive.central))
    return pd.DataFrame(
        {"site_id": [s.site_id for s in sites], "breakeven_capex_usd_per_kw": per_kw}
    )


def usd(value: float) -> str:
    """Money for sentences: -130785.2 -> '-$130,785'."""
    return f"{'-' if value < 0 else ''}${abs(value):,.0f}"


def _ranks(table: pd.DataFrame) -> pd.Series:
    return table.set_index("site_id")["rank"]


def _pct(multiplier: float) -> str:
    return f"{abs(multiplier - 1):.0%} {'lower' if multiplier < 1 else 'higher'}"


def _proxy_sentence(shifts: list[RankShift], n_proxy: int) -> str:
    worst = max(shifts, key=lambda s: s.moved)
    kept = min(s.top_kept for s in shifts)
    return (
        f"If the stand-in tariff used for the {n_proxy} large sites is off by 30% either way, "
        f"{verdict(worst.moved, worst.n_sites)}: at most {worst.moved} of {worst.n_sites} sites "
        f"{moves_word(worst.moved)} {worst.threshold} or more places, and at least {kept} of the "
        "top 10 stay in the top 10."
    )


def _all_demand_sentence(shifts: list[RankShift]) -> str:
    worst = max(shifts, key=lambda s: s.moved)
    return (
        "If every site's demand charge moved 30% together, each site's value would change a lot; "
        f"as for the order, {verdict(worst.moved, worst.n_sites)}: at most {worst.moved} of "
        f"{worst.n_sites} sites {moves_word(worst.moved)} {worst.threshold} or more places."
    )


NEVER_PAYS_BACK = "never pays back, even at $0 battery cost"


def breakeven_label(usd_per_kw: float) -> str:
    """Breakeven battery cost in words. Zero or negative means O&M alone exceeds savings."""
    return NEVER_PAYS_BACK if usd_per_kw <= 0 else f"{usd(usd_per_kw)}/kW"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def headline_sentence(ranking: pd.DataFrame, inputs: EconomicInputs, n_draws: int) -> str:
    """The page's headline. Names the most robust site (rank 1, P10 NPV) and, when it differs,
    the site closest to breaking even, so "the best site" is never ambiguous."""
    top = ranking.sort_values("rank").iloc[0]
    closest = ranking.iloc[int(ranking["breakeven_capex_usd_per_kw"].to_numpy().argmax())]
    capex = inputs.capex_usd_per_kw.central
    any_positive = ranking[ranking["p_npv_positive"] > 0]
    if any_positive.empty:
        viable = (
            f"On demand-charge savings alone, no site pays for itself in any of the "
            f"{n_draws:,} simulated futures"
        )
    else:
        best_count = round(float(any_positive["p_npv_positive"].max()) * n_draws)
        count = len(any_positive)
        viable = (
            f"On demand-charge savings alone, only {count} of {len(ranking)} sites "
            f"{'pays' if count == 1 else 'pay'} for "
            f"{'itself' if count == 1 else 'themselves'} in any of the {n_draws:,} simulated "
            f"futures, and at best in {best_count:,} of them"
        )
    robust = (
        f"{viable}; even the most robust site ({top['site_id']}, ranked 1st by bad-case P10 NPV) "
        f"has a good-case (P90) NPV of {usd(top['npv_p90'])}."
    )
    breakeven = float(closest["breakeven_capex_usd_per_kw"])
    if breakeven <= 0:
        central = " In the central case no site pays back, even at $0 battery cost."
    elif closest["site_id"] == top["site_id"]:
        central = (
            f" In the central case it breaks even only if the battery cost about "
            f"{breakeven_label(breakeven)}, versus {usd(capex)}/kW assumed."
        )
    else:
        by_median = "best by median NPV but " if int(closest["rank_by_p50"]) == 1 else ""
        central = (
            f" The site closest to breaking even is a different one, {closest['site_id']} "
            f"({by_median}ranked {_ordinal(int(closest['rank']))} on robustness): in the central "
            f"case it breaks even only if the battery cost about {breakeven_label(breakeven)}, "
            f"versus {usd(capex)}/kW assumed."
        )
    return (
        robust + central + " Real projects usually stack other revenue (for example "
        "demand-response payments), which this model leaves out."
    )


def _revenue_sentence(ranking: pd.DataFrame, sweep: pd.DataFrame) -> str:
    """How much other revenue would make sites viable, in words (no program amounts assumed)."""
    need = ranking["required_other_revenue_usd_per_kw_year"]
    robust = sweep[sweep["sites_robustly_viable"] > 0]
    tail = (
        f"at {usd(float(robust['other_revenue_usd_per_kw_year'].iloc[0]))}/kW-year, "
        f"{int(robust['sites_robustly_viable'].iloc[0])} of {len(ranking)} sites clear the "
        "robustness bar (P10 NPV above zero)"
        if not robust.empty
        else f"even {usd(float(sweep['other_revenue_usd_per_kw_year'].max()))}/kW-year is not "
        "enough for any site to clear the robustness bar (P10 NPV above zero)"
    )
    least = ranking.iloc[int(need.to_numpy().argmin())]
    return (
        f"To break even in the central case, the site needing the least ({least['site_id']}, "
        f"ranked {_ordinal(int(least['rank']))} on robustness) would need about "
        f"{usd(float(need.min()))}/kW-year of other revenue on top of bill savings and half the "
        f"sites about {usd(float(need.median()))}/kW-year; {tail}. Whether any program pays that "
        "much is not assessed here."
    )


REVENUE_LEVELS = (0.0, 25.0, 50.0, 75.0, 100.0, 150.0, 200.0)


def required_other_revenue(sites: list[SiteEconomics], inputs: EconomicInputs) -> pd.DataFrame:
    """Annual non-bill revenue ($/kW-year, 2025$) each site needs to break even, central case.

    Stands in for revenue streams this model does not include (for example demand-response
    program payments). Zero if the site already breaks even. Assumes the revenue is earned every
    year of the project, independent of the tenant.
    """
    center = central_draws(inputs)
    shortfall = np.maximum(-expected_npv(sites, inputs, center)[:, 0], 0.0)
    factor = annuity_factor(center.discount_rate, inputs.life_years)[0]
    return pd.DataFrame(
        {
            "site_id": [s.site_id for s in sites],
            "required_other_revenue_usd_per_kw_year": shortfall / (inputs.power_kw * factor),
        }
    )


def revenue_sweep(
    npv: np.ndarray,
    draws: Draws,
    inputs: EconomicInputs,
    levels: tuple[float, ...] = REVENUE_LEVELS,
) -> pd.DataFrame:
    """How many sites become viable if every site also earned L $/kW-year of other revenue.

    'Likely viable' = median NPV > 0; 'robustly viable' = P10 NPV > 0 (the ranking's own bar).
    """
    factor = annuity_factor(draws.discount_rate, inputs.life_years)  # (N,)
    rows = []
    for level in levels:
        stacked = npv + level * inputs.power_kw * factor[None, :]
        p10, p50 = np.percentile(stacked, [10, 50], axis=1)
        rows.append(
            {
                "other_revenue_usd_per_kw_year": level,
                "sites_likely_viable": int((p50 > 0).sum()),
                "sites_robustly_viable": int((p10 > 0).sum()),
                "n_sites": npv.shape[0],
            }
        )
    return pd.DataFrame(rows)
