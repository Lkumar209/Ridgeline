"""The M2 masking experiment: inject seeded gaps into real loads and score each imputer."""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial

import numpy as np
import pandas as pd

from ridgeline.config import GapsConfig
from ridgeline.data.schemas import Site
from ridgeline.gaps.evaluate import Imputer, evaluate_gap
from ridgeline.gaps.features import peer_signal, temperature_on_index
from ridgeline.gaps.impute_baseline import seasonal_profile_fill
from ridgeline.gaps.impute_model import RegressionSpec, design_matrix, fill_from_design
from ridgeline.gaps.inject import sample_gaps

BASELINE = "seasonal_profile"
REGRESSION = "regression_weather"
REGRESSION_PEERS = "regression_weather_peers"
METHODS = (BASELINE, REGRESSION, REGRESSION_PEERS)


def build_imputers(
    site: Site,
    sites: list[Site],
    loads: Mapping[str, pd.Series],
    weather: pd.DataFrame,
    cfg: GapsConfig,
) -> dict[str, Imputer]:
    """The three imputers for one site. Peers are other loaded sites of the same type."""
    index = pd.DatetimeIndex(loads[site.site_id].index)
    temp = temperature_on_index(weather, index)
    spec = RegressionSpec(
        cooling_base_c=cfg.cooling_base_c,
        heating_base_c=cfg.heating_base_c,
        ridge_lambda=cfg.ridge_lambda,
    )
    imputers: dict[str, Imputer] = {
        BASELINE: partial(seasonal_profile_fill, window_days=cfg.reference_window_days),
        REGRESSION: partial(
            fill_from_design,
            x=design_matrix(index, temp, None, spec),
            ridge_lambda=spec.ridge_lambda,
        ),
    }
    peers = [
        loads[s.site_id]
        for s in sites
        if s.building_type == site.building_type
        and s.site_id != site.site_id
        and s.site_id in loads
    ]
    if peers:
        x_peers = design_matrix(index, temp, peer_signal(peers, index), spec)
        imputers[REGRESSION_PEERS] = partial(
            fill_from_design, x=x_peers, ridge_lambda=spec.ridge_lambda
        )
    return imputers


def run_experiment(
    sites: list[Site],
    loads: Mapping[str, pd.Series],
    weather_by_county: Mapping[str, pd.DataFrame],
    cfg: GapsConfig,
    score_ids: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Score sites with loaded data. Returns (interval metrics, monthly peak errors).

    `sites` is the full site list: every loaded site can serve as a peer, even when only
    `score_ids` are scored. Sites are processed in site_id order from one seeded generator.
    """
    rng = np.random.default_rng(cfg.seed)
    records: list[dict[str, object]] = []
    peak_tables: list[pd.DataFrame] = []
    for site in sorted(sites, key=lambda s: s.site_id):
        if site.site_id not in loads or (score_ids is not None and site.site_id not in score_ids):
            continue
        actual = loads[site.site_id]
        imputers = build_imputers(site, sites, loads, weather_by_county[site.county_gisjoin], cfg)
        gaps = sample_gaps(
            pd.DatetimeIndex(actual.index),
            cfg.gaps_per_site,
            cfg.min_gap_days,
            cfg.max_gap_days,
            rng,
        )
        for gap_id, gap in enumerate(gaps):
            recs, peaks = evaluate_gap(actual, gap, imputers)
            tags: dict[str, str | int] = {
                "site_id": site.site_id,
                "building_type": site.building_type,
                "gap_id": gap_id,
            }
            records.extend({**r, **tags} for r in recs)
            peak_tables.extend(p.assign(**tags) for p in peaks)
    return pd.DataFrame(records), pd.concat(peak_tables, ignore_index=True)


def summarize(
    metrics: pd.DataFrame, peaks: pd.DataFrame, min_gap_fraction: float = 0.5
) -> pd.DataFrame:
    """One row per method. Peak errors use months at least `min_gap_fraction` inside a gap."""
    covered = peaks[peaks["gap_fraction"] >= min_gap_fraction]
    interval = metrics.groupby("method").agg(
        mae_kw_median=("mae_kw", "median"),
        mape_pct_median=("mape_pct", "median"),
    )
    peak = covered.groupby("method")["peak_error_pct"].agg(
        peak_abs_err_pct_median=lambda s: s.abs().median(),
        peak_abs_err_pct_p90=lambda s: s.abs().quantile(0.9),
        peak_bias_pct_mean="mean",
        months="count",
    )
    return interval.join(peak).reindex([m for m in METHODS if m in interval.index])
