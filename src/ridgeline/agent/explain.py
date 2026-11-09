"""Explain one site's ranking in plain language, grounded only in the numbers provided.

The model gets a short list of facts (rendered by `render_facts`) and nothing else. The output is
rejected if it uses a number or site that is not in those facts, uses "best"/"top" without saying
by which measure, or drops a required caveat (never pays back; proxy tariff).
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel, ConfigDict

from ridgeline.agent.client import LLMClient, LLMRequest
from ridgeline.agent.validators import Checked, ExplanationRules, check_explanation
from ridgeline.ranking.pipeline import breakeven_label, usd


class SiteFacts(BaseModel):
    """Everything the model may say about a site. Money in real 2025 dollars."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: str
    building_type: str
    tariff_is_proxy: bool
    n_sites: int
    n_draws: int
    life_years: int
    capex_usd_per_kw: float
    rank: int
    rank_by_p50: int
    npv_p10: float
    npv_p50: float
    npv_p90: float
    p_npv_positive: float
    breakeven_capex_usd_per_kw: float
    required_other_revenue_usd_per_kw_year: float
    top_site_by_p10: str
    top_site_by_p50: str

    @property
    def never_pays_back(self) -> bool:
        return self.breakeven_capex_usd_per_kw <= 0


def facts_from_ranking(
    ranking: pd.DataFrame,
    site_id: str,
    *,
    n_draws: int,
    life_years: int,
    capex_usd_per_kw: float,
) -> SiteFacts:
    """Facts for `site_id` from a `ranking.csv` table (indexed by site_id or with a column)."""
    table = ranking.reset_index() if "site_id" not in ranking.columns else ranking
    rows = table[table["site_id"] == site_id]
    if rows.empty:
        raise KeyError(f"site {site_id} is not in the ranking")
    row = rows.iloc[0]
    return SiteFacts(
        site_id=site_id,
        building_type=str(row["building_type"]),
        tariff_is_proxy=bool(row["tariff_is_proxy"]),
        n_sites=len(table),
        n_draws=n_draws,
        life_years=life_years,
        capex_usd_per_kw=capex_usd_per_kw,
        rank=int(row["rank"]),
        rank_by_p50=int(row["rank_by_p50"]),
        npv_p10=float(row["npv_p10"]),
        npv_p50=float(row["npv_p50"]),
        npv_p90=float(row["npv_p90"]),
        p_npv_positive=float(row["p_npv_positive"]),
        breakeven_capex_usd_per_kw=float(row["breakeven_capex_usd_per_kw"]),
        required_other_revenue_usd_per_kw_year=float(row["required_other_revenue_usd_per_kw_year"]),
        top_site_by_p10=str(table.sort_values("rank").iloc[0]["site_id"]),
        top_site_by_p50=str(table.sort_values("rank_by_p50").iloc[0]["site_id"]),
    )


def render_facts(f: SiteFacts) -> str:
    """The facts as the model sees them, and as the validator checks numbers against."""
    tariff = (
        "a proxy: MECo G-2 rates applied above G-2's 200 kW limit (an assumption)"
        if f.tariff_is_proxy
        else "MECo G-2, the real published rate"
    )
    lines = [
        f"Site: {f.site_id} ({f.building_type}), one of {f.n_sites} Massachusetts sites.",
        f"Tariff: {tariff}.",
        f"Robustness rank (by bad-case P10 NPV): {f.rank} of {f.n_sites}.",
        f"Rank by median (P50) NPV: {f.rank_by_p50} of {f.n_sites}.",
        f"Most robust site (rank 1 by P10 NPV): {f.top_site_by_p10}.",
        f"Best site by median (P50) NPV: {f.top_site_by_p50}.",
        f"{f.life_years}-year NPV over {f.n_draws:,} simulated futures, real 2025 dollars: "
        f"P10 {usd(f.npv_p10)}, P50 {usd(f.npv_p50)}, P90 {usd(f.npv_p90)}.",
        f"Simulated futures with NPV above zero: {round(f.p_npv_positive * f.n_draws):,} "
        f"of {f.n_draws:,}.",
        f"Battery cost assumed: {usd(f.capex_usd_per_kw)}/kW.",
        f"Breakeven battery cost (central case, demand-charge savings only): "
        f"{breakeven_label(f.breakeven_capex_usd_per_kw)}.",
        f"Other revenue needed to break even at the assumed battery cost (central case): "
        f"{usd(f.required_other_revenue_usd_per_kw_year)}/kW-year.",
        "Reading the NPVs: P10 is the bad case (1 in 10 simulated futures do worse), P50 the "
        "median (half do worse), P90 the good case (9 in 10 do worse).",
        "Not modeled: demand-response or other revenue, supply charges, real meter data.",
    ]
    return "\n".join(lines)


SYSTEM_PROMPT = """\
You explain one site's result from an illustrative battery peak-shaving model to a non-specialist
reader, in one paragraph of 3 to 5 sentences.

Rules:
- Use only the facts given. Every number you write must appear in the facts (you may round, e.g.
  -$217,153 as about -$217k). Do not compute new numbers, such as differences or ratios.
- Refer to sites by their ID. Never say "best", "top" or "worst" without the measure (for example
  "best by median NPV").
- If the breakeven battery cost says the site never pays back, say so plainly.
- If the tariff is a proxy, say that the result rests on a proxy tariff.
- Say what the bad-case (P10) and median (P50) values mean in everyday words. No headings, no lists.
"""


def build_request(facts: SiteFacts) -> LLMRequest:
    return LLMRequest(system=SYSTEM_PROMPT, user=f"<facts>\n{render_facts(facts)}\n</facts>")


def rules_for(facts: SiteFacts) -> ExplanationRules:
    return ExplanationRules(
        facts_text=render_facts(facts),
        site_id=facts.site_id,
        never_pays_back=facts.never_pays_back,
        tariff_is_proxy=facts.tariff_is_proxy,
    )


def explain_site(client: LLMClient, facts: SiteFacts) -> Checked[str]:
    """Ask the model for a paragraph about the site, then check it against the facts."""
    text = client.complete(build_request(facts)).strip()
    return check_explanation(text, rules_for(facts))
