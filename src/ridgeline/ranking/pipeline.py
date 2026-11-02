"""M4 end to end: simulated savings -> Monte Carlo -> robustness ranking -> sensitivity.

Everything here is deterministic given the seed. The scenario comparisons reuse the same
global draws and per-site randomness, so a rank change is caused by the one thing that changed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ridgeline.assumptions import Assumption
from ridgeline.data.schemas import Site
from ridgeline.ranking.metrics import summarize_npv
from ridgeline.ranking.sensitivity import (
    RankShift,
    churn_sentence,
    compare_ranks,
    neighbour_gap,
    tornado,
    verdict,
)
from ridgeline.scenarios.cashflow import Draws
from ridgeline.scenarios.inputs import EconomicInputs, SiteEconomics, churn_hazard
from ridgeline.scenarios.montecarlo import (
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

    base = run(sites)
    base_rank = _ranks(base)
    n_proxy = sum(s.tariff_is_proxy for s in sites)
    shifts: list[RankShift] = []
    for value in PROXY_SWEEP:
        pinned = run(sites, draws.with_value("proxy_demand_multiplier", value))
        change = f"If the proxy demand charge ({n_proxy} sites above 200 kW) were {_pct(value)}"
        shifts.append(compare_ranks(base_rank, _ranks(pinned), f"proxy_demand_x{value:g}", change))
    everyone_proxy = [s.model_copy(update={"tariff_is_proxy": True}) for s in sites]
    for value in PROXY_SWEEP:
        everyone = run(everyone_proxy, draws.with_value("proxy_demand_multiplier", value))
        change = f"If every site's demand charge were {_pct(value)}"
        shifts.append(compare_ranks(base_rank, _ranks(everyone), f"all_demand_x{value:g}", change))

    no_churn = run(sites, churn=False)
    churn_shift = compare_ranks(
        _ranks(no_churn), base_rank, "churn_on_vs_off", "Adding tenant churn"
    )
    shifts.append(churn_shift)

    base = base.merge(breakeven_capex(sites, inputs), on="site_id")
    gap = neighbour_gap(base)
    explanations = {
        "headline": _headline(base, inputs, n_draws),
        "closeness": (
            f"The sites are close together: neighbours in the ranking differ by a median "
            f"${gap:,.0f} of bad-case value, so small input changes can swap neighbours "
            "without changing the overall picture."
        ),
        "proxy_tariff": _proxy_sentence(shifts[:2], n_proxy),
        "all_demand": _all_demand_sentence(shifts[2:4]),
        "tenant_churn": churn_sentence(base, no_churn, churn_shift),
    }
    return RankingResult(base, tornado(sites, inputs), shifts, explanations)


def breakeven_capex(sites: list[SiteEconomics], inputs: EconomicInputs) -> pd.DataFrame:
    """Capex ($/kW, 2025$) at which a site's central-case expected NPV is zero.

    Negative means the site loses money even if the battery were free (O&M exceeds savings).
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
        f"move 3 or more places, and at least {kept} of the top 10 stay in the top 10."
    )


def _all_demand_sentence(shifts: list[RankShift]) -> str:
    worst = max(shifts, key=lambda s: s.moved)
    return (
        "If every site's demand charge moved 30% together, each site's value would change a lot "
        f"but {verdict(worst.moved, worst.n_sites)}: at most {worst.moved} of {worst.n_sites} "
        "sites move 3 or more places."
    )


def _headline(ranking: pd.DataFrame, inputs: EconomicInputs, n_draws: int) -> str:
    best = ranking.iloc[0]
    capex = inputs.capex_usd_per_kw.central
    share = float((ranking["p_npv_positive"] > 0).mean())
    best_breakeven = float(ranking["breakeven_capex_usd_per_kw"].max())
    viable = (
        f"No site pays for itself in any of the {n_draws:,} simulated futures"
        if share == 0
        else f"{share:.0%} of sites pay for themselves in at least some simulated futures"
    )
    return (
        f"{viable}; even the top-ranked site ({best['site_id']}) has a good-case (P90) NPV of "
        f"{usd(best['npv_p90'])}. In the central case the best site breaks even only if the "
        f"battery cost about {usd(best_breakeven)}/kW, versus {usd(capex)}/kW assumed."
    )
