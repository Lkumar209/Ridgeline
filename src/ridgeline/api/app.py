"""FastAPI app: sites, rankings and per-site detail, plus the static map page.

Run with `uv run ridgeline serve`, then open http://127.0.0.1:8000. No auth, no database:
it serves the files `ridgeline rank` wrote. Every response is illustrative.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from ridgeline.api.data import ApiData, MissingResultsError
from ridgeline.api.models import (
    DailyLoad,
    FanPoint,
    Location,
    RankingRow,
    Rankings,
    RevenueLevel,
    SiteDetail,
    SiteSummary,
)
from ridgeline.ranking.pipeline import breakeven_label

WEB_DIR = Path(__file__).resolve().parents[1] / "web"


def create_app(get_data: Callable[[], ApiData], web_dir: Path | None = WEB_DIR) -> FastAPI:
    app = FastAPI(title="Ridgeline (illustrative)", version="0.1.0")

    def data() -> ApiData:
        try:
            return get_data()
        except MissingResultsError as err:
            raise HTTPException(status_code=503, detail=str(err)) from err

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/sites", response_model=list[SiteSummary])
    def sites() -> list[SiteSummary]:
        d = data()
        return [_summary(d, site_id) for site_id in d.ranking.sort_values("rank").index]

    @app.get("/api/rankings", response_model=Rankings)
    def rankings() -> Rankings:
        d = data()
        rows = d.ranking.sort_values("rank").reset_index()
        return Rankings(
            run=d.run,
            explanations=d.explanations,
            rows=[
                RankingRow(**_fields(_labeled(r), RankingRow))
                for r in rows.to_dict(orient="records")
            ],
            revenue_sweep=[
                RevenueLevel(**_fields(r, RevenueLevel))
                for r in d.revenue_sweep.to_dict(orient="records")
            ],
        )

    @app.get("/api/sites/{site_id}", response_model=SiteDetail)
    def site_detail(site_id: str) -> SiteDetail:
        d = data()
        if site_id not in d.sites or site_id not in d.ranking.index:
            raise HTTPException(status_code=404, detail=f"unknown site {site_id}")
        row = {"site_id": site_id, **d.ranking.loc[site_id].to_dict()}
        fan = d.fan[d.fan["site_id"] == site_id].sort_values("year")
        loads = d.daily_load(d.sites[site_id])
        return SiteDetail(
            site=_summary(d, site_id),
            ranking=RankingRow(**_fields(_labeled(row), RankingRow)),
            load_curve=[
                DailyLoad(**_fields(r, DailyLoad)) for r in loads.to_dict(orient="records")
            ],
            fan=[FanPoint(**_fields(r, FanPoint)) for r in fan.to_dict(orient="records")],
        )

    if web_dir is not None:
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


def _labeled(record: dict[Any, Any]) -> dict[Any, Any]:
    """Add the breakeven wording the page shows ("never pays back ..." when <= $0/kW)."""
    return {
        **record,
        "breakeven_label": breakeven_label(float(record["breakeven_capex_usd_per_kw"])),
    }


def _fields(record: dict[Any, Any], model: type[Any]) -> dict[str, Any]:
    """Keep only the keys a response model declares (CSV rows carry extra columns)."""
    return {k: record[k] for k in model.model_fields if k in record}


def _tariff_label(d: ApiData, row: dict[Any, Any]) -> str:
    """The site's tariff by name, saying so when it is a labeled proxy (ADR-010)."""
    tariff_id = row.get("tariff_id")
    known = tariff_id is not None and pd.notna(tariff_id)
    name = d.tariff_names.get(str(tariff_id), "unknown tariff") if known else "unknown tariff"
    return f"{name} (values used as a proxy)" if row["tariff_is_proxy"] else name


def _summary(d: ApiData, site_id: str) -> SiteSummary:
    site = d.sites[site_id]
    row = d.ranking.loc[site_id].to_dict()
    loc = d.locations.loc[site_id].to_dict()
    return SiteSummary(
        site_id=site_id,
        building_type=site.building_type,
        county_name=site.county_name,
        peak_kw=site.peak_kw,
        tariff=_tariff_label(d, row),
        tariff_is_proxy=bool(row["tariff_is_proxy"]),
        rank=int(row["rank"]),
        breakeven_capex_usd_per_kw=float(row["breakeven_capex_usd_per_kw"]),
        breakeven_label=breakeven_label(float(row["breakeven_capex_usd_per_kw"])),
        location=Location(
            lat=float(loc["lat"]), lon=float(loc["lon"]), precision=str(loc["precision"])
        ),
    )
