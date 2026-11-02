"""Command-line entry point: `uv run ridgeline --help`."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import httpx
import typer

from ridgeline.assumptions import load_assumptions
from ridgeline.battery.simulate import History, simulate_sites
from ridgeline.config import Settings, load_settings
from ridgeline.data import comstock
from ridgeline.data.comstock import load_cached_timeseries
from ridgeline.data.schemas import BatterySpec, Site, Tariff
from ridgeline.data.sites import read_sites, write_sites
from ridgeline.data.tariffs import (
    TariffMatchError,
    load_tariff_dir,
    load_tariff_file,
    match_tariff,
    tariff_coverage,
    with_proxies,
)

app = typer.Typer(help="Ridgeline: rank sites for battery peak shaving (illustrative).")


@app.callback()
def _main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING)


@app.command("fetch-data")
def fetch_data(
    dev_subset: bool = typer.Option(
        False, "--dev-subset", help="Download load data for the 10-site dev subset only."
    ),
    config: Path | None = typer.Option(None, help="Config file (default: config/default.yaml)."),
) -> None:
    """Select sites from ComStock metadata and cache their load and weather data."""
    settings = load_settings(config)
    cache_dir = settings.resolve(settings.paths.cache_dir)
    with httpx.Client() as client:
        meta = comstock.fetch_metadata(settings.comstock, cache_dir, client)
        sites = comstock.select_sites(meta, settings.site_selection)
        write_sites(sites, settings.resolve(settings.paths.sites_file))
        targets = [s for s in sites if s.dev_subset] if dev_subset else sites
        with typer.progressbar(targets, label="load profiles") as bar:
            for site in bar:
                comstock.fetch_timeseries(settings.comstock, site.bldg_id, cache_dir, client)
        for county in sorted({s.county_gisjoin for s in targets}):
            comstock.fetch_weather(settings.comstock, county, cache_dir, client)
    _report(settings, sites, targets, cache_dir)


def _report(settings: Settings, sites: list[Site], targets: list[Site], cache_dir: Path) -> None:
    typer.echo(f"selected {len(sites)} sites; cached load data for {len(targets)}")
    for label, counts in (
        ("building type", Counter(s.building_type for s in sites)),
        ("county", Counter(s.county_name for s in sites)),
        ("utility EIA id", Counter(s.utility_eiaid for s in sites)),
        ("PAR tier", Counter(s.par_tier for s in sites)),
    ):
        typer.echo(f"  {label}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    tariffs = _load_tariffs(settings)
    coverage = tariff_coverage(sites, tariffs)
    typer.echo(
        f"  tariffs loaded: {len(tariffs)}; sites matched: {len(coverage.matched)}, "
        f"unmatched: {len(coverage.unmatched)}, ambiguous: {len(coverage.ambiguous)}"
    )
    size_mb = sum(p.stat().st_size for p in cache_dir.rglob("*") if p.is_file()) / 1e6
    typer.echo(f"  cache size: {size_mb:.1f} MB at {cache_dir}")


def _load_tariffs(settings: Settings) -> list[Tariff]:
    """Real tariff files plus the configured, labeled proxies (ADR-010)."""
    real = load_tariff_dir(settings.resolve(settings.paths.tariffs_dir), _power_factor())
    return with_proxies(real, settings.tariff_proxies)


def _power_factor() -> float:
    value = load_assumptions()["power_factor_for_kva_demand"].value
    if isinstance(value, str):
        raise ValueError("power_factor_for_kva_demand must be numeric")
    return float(value)


def _not_yet(milestone: str) -> None:
    typer.echo(f"not implemented until {milestone}", err=True)
    raise typer.Exit(code=1)


@app.command()
def simulate(
    dev_subset: bool = typer.Option(False, "--dev-subset", help="Only the 10 dev sites."),
    tariff_override: Path | None = typer.Option(
        None,
        help="Apply this tariff file to every site, ignoring matching. Development only; "
        "results are labeled with the tariff id.",
    ),
    optimal: bool = typer.Option(True, help="Also solve the perfect-foresight LP bound."),
    wraparound_lookahead: bool = typer.Option(
        False,
        "--wraparound-lookahead",
        help="Seed the first month's threshold from the last month of the same year. This uses "
        "future information; for comparison only (default: battery idle in the first month).",
    ),
    config: Path | None = typer.Option(None, help="Config file (default: config/default.yaml)."),
) -> None:
    """Simulate battery dispatch and monthly bills for each site (illustrative)."""
    settings = load_settings(config)
    sites = read_sites(settings.resolve(settings.paths.sites_file))
    sites = [s for s in sites if s.dev_subset] if dev_subset else sites
    tariffs = _tariffs_for(settings, sites, tariff_override)
    cache = settings.resolve(settings.paths.cache_dir) / "comstock" / "timeseries"
    missing = [s.site_id for s in sites if not (cache / f"{s.bldg_id}.parquet").exists()]
    if missing:
        typer.echo(f"no cached load for {missing}; run `ridgeline fetch-data` first", err=True)
        raise typer.Exit(code=1)
    loads = {s.site_id: load_cached_timeseries(cache / f"{s.bldg_id}.parquet") for s in sites}
    spec = BatterySpec.from_assumptions(load_assumptions())
    history: History = "wraparound" if wraparound_lookahead else "causal"
    monthly, summary = simulate_sites(
        sites, loads, tariffs, spec, with_optimal=optimal, history=history
    )
    if wraparound_lookahead:
        typer.echo("*** LOOKAHEAD: first month uses the last month of the same year. ***")

    out_dir = settings.resolve(settings.paths.cache_dir) / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(out_dir / "simulate_monthly.csv", index=False)
    summary.to_csv(out_dir / "simulate_summary.csv", index=False)
    if summary["tariff_is_test_fixture"].any():
        typer.echo("*** TEST FIXTURE TARIFF: dollar figures below are NOT real. ***")
    if summary["tariff_is_proxy"].any():
        typer.echo("Note: tariff_is_proxy rows use G-2 values beyond its eligibility (ASSUMPTION).")
    columns = [c for c in SUMMARY_COLUMNS if c in summary]
    typer.echo(summary[columns].round(2).to_string(index=False))
    typer.echo(f"wrote {out_dir}/simulate_monthly.csv and simulate_summary.csv (illustrative)")


SUMMARY_COLUMNS = [
    "site_id",
    "building_type",
    "peak_kw",
    "tariff_id",
    "tariff_is_proxy",
    "base_bill_usd",
    "practical_savings_usd",
    "oracle_savings_usd",
    "optimal_savings_usd",
    "capture_ratio",
]


def _tariffs_for(settings: Settings, sites: list[Site], override: Path | None) -> dict[str, Tariff]:
    """Matched tariff per site. Exits non-zero listing every site that matches 0 or 2+."""
    if override is not None:
        (tariff,) = load_tariff_file(override, _power_factor())
        return {s.site_id: tariff for s in sites}
    tariffs = _load_tariffs(settings)
    matched, errors = {}, []
    for site in sites:
        try:
            matched[site.site_id] = match_tariff(site, tariffs)
        except TariffMatchError as err:
            errors.append(str(err))
    if errors:
        typer.echo(f"{len(errors)} of {len(sites)} sites have no unique tariff:", err=True)
        for line in errors:
            typer.echo(f"  {line}", err=True)
        raise typer.Exit(code=1)
    return matched


@app.command()
def rank() -> None:
    """Run the Monte Carlo and rank sites (M4)."""
    _not_yet("M4")


@app.command()
def serve() -> None:
    """Serve the API and map UI (M5)."""
    _not_yet("M5")
