"""Fixed, hand-built inputs for scenario and ranking tests (independent of assumptions.yaml)."""

from __future__ import annotations

from ridgeline.scenarios.inputs import EconomicInputs, Range, SiteEconomics


def inputs(**overrides: object) -> EconomicInputs:
    fields: dict[str, object] = {
        "capex_usd_per_kw": Range(800.0, 1000.0, 1200.0),
        "om_usd_per_kw_year": Range(10.0, 20.0, 30.0),
        "discount_rate": Range(0.03, 0.05, 0.08),
        "escalation": Range(-0.01, 0.0, 0.02),
        "incentive": Range(0.0, 0.15, 0.3),
        "capacity_fade": Range(0.01, 0.02, 0.03),
        "proxy_demand_multiplier": Range(0.7, 1.0, 1.3),
        "churn_multiplier": Range(0.5, 1.0, 2.0),
        "savings_noise_sd": 0.1,
        "life_years": 15,
        "power_kw": 100.0,
    }
    fields.update(overrides)
    return EconomicInputs(**fields)  # type: ignore[arg-type]


def site(
    i: int,
    demand: float,
    energy: float = -100.0,
    *,
    proxy: bool = False,
    hazard: float = 0.05,
    btype: str = "MediumOffice",
) -> SiteEconomics:
    return SiteEconomics(
        site_id=f"s{i}",
        bldg_id=i,
        building_type=btype,
        tariff_is_proxy=proxy,
        demand_savings_usd=demand,
        energy_savings_usd=energy,
        churn_hazard=hazard,
    )


def five_sites() -> list[SiteEconomics]:
    return [
        site(1, 9000.0, btype="RetailStripmall", hazard=0.10),
        site(2, 7000.0, proxy=True, btype="Outpatient", hazard=0.04),
        site(3, 6000.0, btype="PrimarySchool", hazard=0.01),
        site(4, 6500.0, proxy=True, btype="FullServiceRestaurant", hazard=0.12),
        site(5, 3000.0, btype="Warehouse", hazard=0.06),
    ]
