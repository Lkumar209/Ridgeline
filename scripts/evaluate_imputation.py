"""Run the M2 gap-imputation experiment on cached sites and write results to docs/m2/.

Usage: uv run python scripts/evaluate_imputation.py [--dev-subset]
Requires `uv run ridgeline fetch-data` first (all 40 sites, so every type has peers).
"""

from __future__ import annotations

import argparse
import time

import pandas as pd

from ridgeline.config import REPO_ROOT, load_settings
from ridgeline.data.comstock import load_cached_timeseries
from ridgeline.data.sites import read_sites
from ridgeline.data.weather import load_weather
from ridgeline.gaps.experiment import run_experiment, summarize

OUT_DIR = REPO_ROOT / "docs" / "m2"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dev-subset", action="store_true", help="score only the 10 dev sites")
    args = parser.parse_args()

    settings = load_settings()
    cache = settings.resolve(settings.paths.cache_dir) / "comstock"
    sites = read_sites(settings.resolve(settings.paths.sites_file))
    loads = {
        s.site_id: load_cached_timeseries(cache / "timeseries" / f"{s.bldg_id}.parquet")
        for s in sites
        if (cache / "timeseries" / f"{s.bldg_id}.parquet").exists()
    }
    weather = {
        c: load_weather(cache / "weather" / f"{c}.csv") for c in {s.county_gisjoin for s in sites}
    }
    score_ids = {s.site_id for s in sites if s.dev_subset} if args.dev_subset else None

    t0 = time.perf_counter()
    # Pass every site so peers come from all loaded sites, scored or not.
    metrics, peaks = run_experiment(sites, loads, weather, settings.gaps, score_ids)
    elapsed = time.perf_counter() - t0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(OUT_DIR / "interval_metrics.csv", index=False, float_format="%.4f")
    peaks.to_csv(OUT_DIR / "monthly_peak_errors.csv", index=False, float_format="%.4f")
    summary = summarize(metrics, peaks)
    summary.to_csv(OUT_DIR / "summary.csv", float_format="%.3f")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(summary.round(2))
    n_sites = metrics["site_id"].nunique()
    print(f"{n_sites} sites x {settings.gaps.gaps_per_site} gaps in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
