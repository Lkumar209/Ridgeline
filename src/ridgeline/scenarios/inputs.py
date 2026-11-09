"""Typed economic inputs for the Monte Carlo, built from assumptions.yaml and simulation output.

Every number used by the cash-flow model comes through here, so the provenance rule (source URL
or ASSUMPTION) is enforced in one place.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from ridgeline.assumptions import Assumption


class SiteEconomics(BaseModel):
    """One site's year-1 savings from M3 (practical controller) and its churn hazard."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: str
    bldg_id: int
    building_type: str
    tariff_is_proxy: bool
    tariff_id: str | None = Field(default=None, description="Tariff the savings were billed on")
    demand_savings_usd: float = Field(description="Year-1 demand-charge savings")
    energy_savings_usd: float = Field(description="Year-1 energy savings (negative = losses)")
    churn_hazard: float = Field(ge=0, le=1, description="Base annual probability tenant leaves")


@dataclass(frozen=True)
class Range:
    low: float
    central: float
    high: float

    @classmethod
    def of(cls, a: Assumption, scale: float = 1.0) -> Range:
        if a.low is None or a.high is None:
            raise ValueError("assumption has no range")
        return cls(a.low * scale, a.number * scale, a.high * scale)


@dataclass(frozen=True)
class EconomicInputs:
    """Uncertain inputs (as ranges) plus fixed ones. Money in real 2025 dollars."""

    capex_usd_per_kw: Range
    om_usd_per_kw_year: Range
    discount_rate: Range
    escalation: Range
    incentive: Range
    capacity_fade: Range
    proxy_demand_multiplier: Range
    churn_multiplier: Range
    savings_noise_sd: float
    life_years: int
    power_kw: float

    UNCERTAIN = (
        "capex_usd_per_kw",
        "om_usd_per_kw_year",
        "discount_rate",
        "escalation",
        "incentive",
        "capacity_fade",
        "proxy_demand_multiplier",
        "churn_multiplier",
    )

    @classmethod
    def from_assumptions(cls, a: dict[str, Assumption], power_kw: float) -> EconomicInputs:
        dollars = a["usd_2022_to_2025_factor"].number
        return cls(
            capex_usd_per_kw=Range.of(a["battery_capex_usd_per_kw"], dollars),
            om_usd_per_kw_year=Range.of(a["battery_fixed_om_usd_per_kw_year"], dollars),
            discount_rate=Range.of(a["discount_rate_real"]),
            escalation=Range.of(a["tariff_escalation_real"]),
            incentive=Range.of(a["upfront_incentive_fraction"]),
            capacity_fade=Range.of(a["capacity_fade_per_year"]),
            proxy_demand_multiplier=Range.of(a["proxy_demand_charge_multiplier"]),
            churn_multiplier=Range.of(a["tenant_churn_multiplier"]),
            savings_noise_sd=a["annual_savings_noise_sd"].number,
            life_years=int(a["project_life_years"].number),
            power_kw=power_kw,
        )


def churn_hazard(a: dict[str, Assumption], building_type: str) -> float:
    key = f"tenant_churn_hazard_{building_type}"
    if key not in a:
        raise KeyError(f"no churn hazard assumption for {building_type} ({key})")
    return a[key].number
