"""NREL ComStock loader: metadata screening, site selection, and timeseries normalization.

Pure functions (`slim_metadata`, `select_sites`, `normalize_timeseries`) are separated from I/O
(`fetch_*`) so selection and conversion logic can be tested offline on small fixtures.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from ridgeline.config import ComStockConfig, SiteSelectionConfig
from ridgeline.data.cache import download
from ridgeline.data.schemas import ParTier, Site
from ridgeline.data.timestamps import standard_time_ending_to_utc_start

log = logging.getLogger(__name__)

INTERVAL = timedelta(minutes=15)
INTERVALS_PER_YEAR = 365 * 96
HOURS_PER_YEAR = 365 * 24
TOTAL_KWH_COL = "out.electricity.total.energy_consumption"
LIGHTING_KWH_COL = "out.electricity.interior_lighting.energy_consumption"
SIMULATED_STATE = "Massachusetts"
TIERS: tuple[ParTier, ...] = ("low", "mid", "high")

# Raw metadata column -> our name. Only these columns are kept in the cache.
METADATA_COLUMNS = {
    "bldg_id": "bldg_id",
    "weight": "weight",
    "in.comstock_building_type": "building_type",
    "in.nhgis_county_gisjoin": "county_gisjoin",
    "in.county_name": "county_name",
    "in.nhgis_tract_gisjoin": "tract_gisjoin",
    "in.as_simulated_state_name": "as_simulated_state",
    "in.sqft..ft2": "sqft",
    "out.utility_bills.electricity_utility_eia_id": "utility_eiaid",
    "out.electricity.total.peak_demand..kw": "peak_kw",
    "out.electricity.total.energy_consumption..kwh": "annual_kwh",
}


# --- URLs -------------------------------------------------------------------------------


def metadata_url(cfg: ComStockConfig, county: str) -> str:
    return (
        f"{cfg.base_url}metadata_and_annual_results/by_state_and_county/full/parquet/"
        f"state={cfg.state}/county={county}/{cfg.state}_{county}_baseline.parquet"
    )


def timeseries_url(cfg: ComStockConfig, bldg_id: int) -> str:
    return (
        f"{cfg.base_url}timeseries_individual_buildings/by_state/upgrade={cfg.upgrade}/"
        f"state={cfg.state}/{bldg_id}-{cfg.upgrade}.parquet"
    )


def weather_url(cfg: ComStockConfig, county: str) -> str:
    return f"{cfg.base_url}weather/amy2018/{county}_2018.csv"


# --- Pure transforms --------------------------------------------------------------------


def slim_metadata(raw: pd.DataFrame) -> pd.DataFrame:
    """Reduce raw ComStock metadata to one row per building simulated in Massachusetts.

    Raw files hold one row per building x census-tract allocation, and include buildings
    "as simulated" in neighboring states. We keep MA-simulated buildings only and, for each
    building, the allocation row with the largest weight (ties broken by tract code).
    """
    df = raw[list(METADATA_COLUMNS)].rename(columns=METADATA_COLUMNS)
    df = df[df["as_simulated_state"] == SIMULATED_STATE]
    df = df.sort_values(["bldg_id", "weight", "tract_gisjoin"], ascending=[True, False, True])
    df = df.drop_duplicates("bldg_id", keep="first").drop(columns=["as_simulated_state"])
    df["utility_eiaid"] = pd.to_numeric(df["utility_eiaid"], errors="coerce").astype("Int64")
    df["mean_kw"] = df["annual_kwh"] / HOURS_PER_YEAR
    return df.reset_index(drop=True)


def combine_metadata(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    """Merge slimmed per-county frames; a building listed in two counties keeps its max weight."""
    df = pd.concat(frames, ignore_index=True)
    df = df.sort_values(["bldg_id", "weight", "county_gisjoin"], ascending=[True, False, True])
    return df.drop_duplicates("bldg_id", keep="first").reset_index(drop=True)


def screen_candidates(meta: pd.DataFrame, cfg: SiteSelectionConfig) -> pd.DataFrame:
    """Apply type, peak-size, and utility filters, then label each site's PAR tercile by type."""
    keep = (
        meta["building_type"].isin(cfg.building_types)
        & meta["peak_kw"].between(cfg.peak_kw_min, cfg.peak_kw_max)
        & meta["mean_kw"].gt(0)
        & meta["utility_eiaid"].notna()
    )
    if cfg.utility_eiaids is not None:
        keep &= meta["utility_eiaid"].isin(cfg.utility_eiaids)
    df = meta[keep].copy()
    df["par"] = df["peak_kw"] / df["mean_kw"]
    df["par_tier"] = df.groupby("building_type")["par"].transform(_tercile_labels)
    return df.sort_values("bldg_id").reset_index(drop=True)


def _tercile_labels(par: pd.Series) -> pd.Series:
    ranks = par.rank(method="first")
    return pd.Series(pd.qcut(ranks, q=3, labels=list(TIERS)).astype(str), index=par.index)


def select_sites(meta: pd.DataFrame, cfg: SiteSelectionConfig) -> list[Site]:
    """Seeded, stratified selection: per building type, draw a fixed quota from each PAR tier.

    The same metadata and config always produce the same sites. Raises if any stratum
    has fewer candidates than its quota, rather than silently returning fewer sites.
    """
    candidates = screen_candidates(meta, cfg)
    rng = np.random.default_rng(cfg.seed)
    q = cfg.par_tier_quota
    quota = {"low": q.low, "mid": q.mid, "high": q.high}

    per_type: list[list[pd.Series]] = []
    for type_index, btype in enumerate(cfg.building_types):
        by_tier: dict[str, list[pd.Series]] = {}
        for tier in TIERS:
            pool = candidates[
                (candidates["building_type"] == btype) & (candidates["par_tier"] == tier)
            ]
            if len(pool) < quota[tier]:
                raise ValueError(
                    f"only {len(pool)} {btype} candidates in PAR tier {tier!r}, need {quota[tier]}"
                )
            picks = rng.choice(len(pool), size=quota[tier], replace=False)
            by_tier[tier] = [pool.iloc[int(i)] for i in sorted(picks)]
        per_type.append(_interleave_tiers(by_tier, start=type_index))

    ordered = _round_robin(per_type)
    if cfg.replace_utility_eiaids:
        ordered = _replace_utilities(ordered, candidates, cfg)
    return [_row_to_site(row, dev_subset=i < cfg.dev_subset_size) for i, row in enumerate(ordered)]


def _replace_utilities(
    ordered: list[pd.Series], candidates: pd.DataFrame, cfg: SiteSelectionConfig
) -> list[pd.Series]:
    """Swap out sites served by `cfg.replace_utility_eiaids` (ADR-010).

    Each replacement comes from the same building type and PAR tier, from a utility not being
    replaced, and keeps the original's position (so the dev subset keeps its size and mix).
    A separate seeded generator is used, so every site that is not replaced stays identical.
    """
    rng = np.random.default_rng([cfg.seed, 1])
    replace = set(cfg.replace_utility_eiaids)
    taken = {int(row["bldg_id"]) for row in ordered}
    out = []
    for row in ordered:
        if int(row["utility_eiaid"]) not in replace:
            out.append(row)
            continue
        pool = candidates[
            (candidates["building_type"] == row["building_type"])
            & (candidates["par_tier"] == row["par_tier"])
            & ~candidates["utility_eiaid"].isin(replace)
            & ~candidates["bldg_id"].isin(taken)
        ]
        if pool.empty:
            raise ValueError(f"no replacement for bldg {row['bldg_id']} in its stratum")
        pick = pool.iloc[int(rng.integers(len(pool)))]
        taken.add(int(pick["bldg_id"]))
        out.append(pick)
    return out


def _interleave_tiers(by_tier: dict[str, list[pd.Series]], start: int) -> list[pd.Series]:
    """Order one type's picks by cycling tiers, starting at a type-specific tier."""
    rotation = [TIERS[(start + k) % len(TIERS)] for k in range(len(TIERS))]
    queues = {tier: list(rows) for tier, rows in by_tier.items()}
    out: list[pd.Series] = []
    while any(queues.values()):
        for tier in rotation:
            if queues[tier]:
                out.append(queues[tier].pop(0))
    return out


def _round_robin(groups: list[list[pd.Series]]) -> list[pd.Series]:
    """Take the first item of every group, then the second, and so on."""
    out: list[pd.Series] = []
    for rank in range(max(len(g) for g in groups)):
        out.extend(g[rank] for g in groups if rank < len(g))
    return out


def _row_to_site(row: pd.Series, *, dev_subset: bool) -> Site:
    return Site(
        site_id=f"cs-{int(row['bldg_id'])}",
        bldg_id=int(row["bldg_id"]),
        building_type=str(row["building_type"]),
        county_gisjoin=str(row["county_gisjoin"]),
        county_name=str(row["county_name"]),
        tract_gisjoin=str(row["tract_gisjoin"]),
        utility_eiaid=int(row["utility_eiaid"]),
        sqft=float(row["sqft"]),
        peak_kw=float(row["peak_kw"]),
        mean_kw=float(row["mean_kw"]),
        par_tier=row["par_tier"],
        dev_subset=dev_subset,
    )


def normalize_timeseries(raw: pd.DataFrame) -> pd.Series:
    """Raw ComStock building timeseries -> average kW per interval, indexed by UTC interval start.

    Raises if the series is not a full, regular year of 15-min intervals.
    """
    index = standard_time_ending_to_utc_start(raw["timestamp"], INTERVAL)
    kw = raw[TOTAL_KWH_COL].to_numpy(dtype=float) * (timedelta(hours=1) / INTERVAL)
    series = pd.Series(kw, index=index, name="kw")
    check_full_year(series)
    return series


def check_full_year(series: pd.Series) -> None:
    if len(series) != INTERVALS_PER_YEAR:
        raise ValueError(f"expected {INTERVALS_PER_YEAR} intervals, got {len(series)}")
    index = pd.DatetimeIndex(series.index)
    if not (index[1:] - index[:-1] == INTERVAL).all():
        raise ValueError("timeseries is not regularly spaced")
    if series.isna().any() or (series < 0).any():
        raise ValueError("timeseries has missing or negative values")


# --- I/O --------------------------------------------------------------------------------


def fetch_metadata(cfg: ComStockConfig, cache_dir: Path, client: httpx.Client) -> pd.DataFrame:
    """Download each county's metadata once, slim it, cache the slim copy, drop the raw file."""
    frames = []
    for county in cfg.counties:
        slim_path = cache_dir / "comstock" / "metadata" / f"{county}.parquet"
        if not slim_path.exists():
            raw_path = slim_path.with_suffix(".raw.parquet")
            download(metadata_url(cfg, county), raw_path, client)
            columns = list(METADATA_COLUMNS)
            slim_metadata(pd.read_parquet(raw_path, columns=columns)).to_parquet(slim_path)
            raw_path.unlink()
        frames.append(pd.read_parquet(slim_path))
    return combine_metadata(frames)


def fetch_timeseries(
    cfg: ComStockConfig, bldg_id: int, cache_dir: Path, client: httpx.Client
) -> pd.Series:
    """Download, normalize and cache one building's load as UTC interval-start kW."""
    slim_path = cache_dir / "comstock" / "timeseries" / f"{bldg_id}.parquet"
    if not slim_path.exists():
        raw_path = slim_path.with_suffix(".raw.parquet")
        download(timeseries_url(cfg, bldg_id), raw_path, client)
        raw = pd.read_parquet(raw_path, columns=["timestamp", TOTAL_KWH_COL])
        normalize_timeseries(raw).to_frame().to_parquet(slim_path)
        raw_path.unlink()
    return load_cached_timeseries(slim_path)


def load_cached_timeseries(path: Path) -> pd.Series:
    series = pd.read_parquet(path)["kw"]
    check_full_year(series)
    return series


def fetch_weather(cfg: ComStockConfig, county: str, cache_dir: Path, client: httpx.Client) -> Path:
    return download(
        weather_url(cfg, county), cache_dir / "comstock" / "weather" / f"{county}.csv", client
    )
