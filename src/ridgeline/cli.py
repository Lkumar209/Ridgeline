"""Command-line entry point: `uv run ridgeline --help`."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path

import httpx
import typer

from ridgeline.assumptions import load_assumptions
from ridgeline.config import Settings, load_settings
from ridgeline.data import comstock
from ridgeline.data.schemas import Site
from ridgeline.data.sites import write_sites
from ridgeline.data.tariffs import load_tariff_dir, tariff_coverage

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
    tariffs = load_tariff_dir(settings.resolve(settings.paths.tariffs_dir), _power_factor())
    coverage = tariff_coverage(sites, tariffs)
    typer.echo(
        f"  tariffs loaded: {len(tariffs)}; sites matched: {len(coverage.matched)}, "
        f"unmatched: {len(coverage.unmatched)}, ambiguous: {len(coverage.ambiguous)}"
    )
    size_mb = sum(p.stat().st_size for p in cache_dir.rglob("*") if p.is_file()) / 1e6
    typer.echo(f"  cache size: {size_mb:.1f} MB at {cache_dir}")


def _power_factor() -> float:
    value = load_assumptions()["power_factor_for_kva_demand"].value
    if isinstance(value, str):
        raise ValueError("power_factor_for_kva_demand must be numeric")
    return float(value)


def _not_yet(milestone: str) -> None:
    typer.echo(f"not implemented until {milestone}", err=True)
    raise typer.Exit(code=1)


@app.command()
def simulate() -> None:
    """Simulate battery dispatch and bills per site (M3)."""
    _not_yet("M3")


@app.command()
def rank() -> None:
    """Run the Monte Carlo and rank sites (M4)."""
    _not_yet("M4")


@app.command()
def serve() -> None:
    """Serve the API and map UI (M5)."""
    _not_yet("M5")
