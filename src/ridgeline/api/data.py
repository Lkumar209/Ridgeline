"""Everything the API serves, loaded once from `ridgeline rank` outputs and the data cache.

The API never runs the simulation or the Monte Carlo itself: it reads the files `rank` wrote, so
responses are fast and match `docs/m4/` exactly.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from ridgeline.assumptions import load_assumptions
from ridgeline.config import Settings
from ridgeline.data.comstock import load_cached_timeseries
from ridgeline.data.locations import read_locations
from ridgeline.data.schemas import LOCAL_TZ, Site
from ridgeline.data.sites import read_sites
from ridgeline.data.tariffs import load_tariff_dir, with_proxies

RESULT_FILES = ("ranking.csv", "fan.csv", "explanations.json", "revenue_sweep.csv")


class MissingResultsError(RuntimeError):
    """Ranking outputs are not there yet: run `ridgeline rank` first."""


@dataclass(frozen=True)
class ApiData:
    sites: dict[str, Site]
    locations: pd.DataFrame  # indexed by site_id: lat, lon, precision
    ranking: pd.DataFrame  # indexed by site_id
    fan: pd.DataFrame  # site_id, year, p10, p50, p90
    revenue_sweep: pd.DataFrame
    explanations: dict[str, str]
    run: dict[str, float | int]
    daily_load: Callable[[Site], pd.DataFrame]  # date, peak_kw, mean_kw (empty if no data)
    tariff_names: dict[str, str] = field(default_factory=dict)  # tariff_id -> tariff name


def daily_load(series: pd.Series) -> pd.DataFrame:
    """15-min kW -> one row per local day with that day's peak and mean kW."""
    local = series.tz_convert(LOCAL_TZ)
    days = pd.DatetimeIndex(local.index).date
    grouped = local.groupby(days)
    frame = pd.DataFrame({"peak_kw": grouped.max(), "mean_kw": grouped.mean()})
    frame.index = [str(d) for d in frame.index]
    return frame.rename_axis("date").reset_index()


def load_api_data(settings: Settings) -> ApiData:
    results = settings.resolve(settings.paths.results_dir)
    missing = [name for name in RESULT_FILES if not (results / name).exists()]
    if missing:
        raise MissingResultsError(
            f"missing {', '.join(missing)} in {results}; run `ridgeline rank` first"
        )
    info = json.loads((results / "explanations.json").read_text())
    cache = settings.resolve(settings.paths.cache_dir) / "comstock" / "timeseries"

    def site_daily_load(site: Site) -> pd.DataFrame:
        path = cache / f"{site.bldg_id}.parquet"
        if not path.exists():
            return pd.DataFrame(columns=["date", "peak_kw", "mean_kw"])
        return daily_load(load_cached_timeseries(path))

    sites = read_sites(settings.resolve(settings.paths.sites_file))
    tariffs = with_proxies(
        load_tariff_dir(
            settings.resolve(settings.paths.tariffs_dir),
            load_assumptions()["power_factor_for_kva_demand"].number,
        ),
        settings.tariff_proxies,
    )
    return ApiData(
        sites={s.site_id: s for s in sites},
        locations=read_locations(Path(settings.resolve(settings.paths.locations_file))).set_index(
            "site_id"
        ),
        ranking=pd.read_csv(results / "ranking.csv").set_index("site_id"),
        fan=pd.read_csv(results / "fan.csv"),
        revenue_sweep=pd.read_csv(results / "revenue_sweep.csv"),
        explanations=info["explanations"],
        run=info["run"],
        daily_load=site_daily_load,
        tariff_names={t.tariff_id: t.name for t in tariffs},
    )
