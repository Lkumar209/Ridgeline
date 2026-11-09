"""Response models: the API's contract with the map page (and any other client)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class Location(_Out):
    lat: float
    lon: float
    precision: str


class SiteSummary(_Out):
    site_id: str
    building_type: str
    county_name: str
    peak_kw: float
    tariff: str
    tariff_is_proxy: bool
    rank: int
    breakeven_capex_usd_per_kw: float
    breakeven_label: str
    location: Location


class RankingRow(_Out):
    rank: int
    site_id: str
    building_type: str
    tariff_is_proxy: bool
    npv_p10: float
    npv_p50: float
    npv_p90: float
    p_npv_positive: float
    rank_by_p50: int
    breakeven_capex_usd_per_kw: float
    breakeven_label: str
    required_other_revenue_usd_per_kw_year: float


class RevenueLevel(_Out):
    other_revenue_usd_per_kw_year: float
    sites_likely_viable: int
    sites_robustly_viable: int


class Rankings(_Out):
    illustrative: bool = True
    run: dict[str, float | int]
    explanations: dict[str, str]
    rows: list[RankingRow]
    revenue_sweep: list[RevenueLevel]


class DailyLoad(_Out):
    date: str
    peak_kw: float
    mean_kw: float


class FanPoint(_Out):
    year: int
    p10: float
    p50: float
    p90: float


class SiteDetail(_Out):
    illustrative: bool = True
    site: SiteSummary
    ranking: RankingRow
    load_curve: list[DailyLoad]
    fan: list[FanPoint]
