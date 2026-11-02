"""End to end on committed fixtures: raw ComStock rows -> dispatch, bills -> Monte Carlo -> rank."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd

from ridgeline.battery.simulate import annual_summary, simulate_site
from ridgeline.data.comstock import TOTAL_KWH_COL
from ridgeline.data.timestamps import standard_time_ending_to_utc_start
from ridgeline.ranking.pipeline import rank_sites
from ridgeline.scenarios.inputs import SiteEconomics
from tests.battery_helpers import SPEC, flat_demand_tariff
from tests.scenario_helpers import inputs

TYPES = {68361: "MediumOffice", 45533: "PrimarySchool", 31197: "Warehouse"}


def test_fixture_loads_flow_through_to_a_ranking(raw_sample: pd.DataFrame) -> None:
    economics = []
    for bldg_id in sorted(TYPES):
        rows = raw_sample[raw_sample["bldg_id"] == bldg_id]
        q = timedelta(minutes=15)
        index = standard_time_ending_to_utc_start(pd.DatetimeIndex(rows["timestamp"]), q)
        load = pd.Series(rows[TOTAL_KWH_COL].to_numpy() * 4, index=index)
        # One series with a February and a July fortnight. February has no history (idle, by
        # the causal rule), so July's threshold comes from February. Simulating each fortnight
        # alone would leave both idle (regression: an earlier version of this test did that).
        summary = annual_summary(simulate_site(load, flat_demand_tariff(), SPEC))
        economics.append(
            SiteEconomics(
                site_id=f"cs-{bldg_id}",
                bldg_id=bldg_id,
                building_type=TYPES[bldg_id],
                tariff_is_proxy=False,
                demand_savings_usd=summary["practical_demand_savings_usd"],
                energy_savings_usd=summary["practical_energy_savings_usd"],
                churn_hazard=0.05,
            )
        )
    result = rank_sites(economics, inputs(power_kw=SPEC.power_kw), n_draws=200, seed=1)
    ranking = result.ranking
    assert sorted(ranking["rank"]) == [1, 2, 3]
    assert (ranking["npv_p10"] <= ranking["npv_p50"]).all()
    assert (ranking["npv_p50"] <= ranking["npv_p90"]).all()
    # Demand savings were positive for at least one site, so the pipeline did real work.
    assert max(e.demand_savings_usd for e in economics) > 0
    assert all(sentence for sentence in result.explanations.values())
