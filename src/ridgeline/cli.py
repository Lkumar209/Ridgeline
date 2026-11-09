"""Command-line entry point: `uv run ridgeline --help`."""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from pathlib import Path

import httpx
import pandas as pd
import typer

from ridgeline.agent.client import (
    KEY_ENV_VAR,
    AgentSettings,
    AnthropicClient,
    LLMClient,
    has_api_key,
    resolve_model,
)
from ridgeline.assumptions import load_assumptions
from ridgeline.battery.simulate import History, simulate_sites
from ridgeline.config import Settings, load_settings
from ridgeline.data import comstock
from ridgeline.data.cache import download
from ridgeline.data.comstock import load_cached_timeseries
from ridgeline.data.locations import load_geojson, puma_centroids, site_locations
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
from ridgeline.ranking.pipeline import rank_sites, site_economics
from ridgeline.results import cached_savings
from ridgeline.scenarios.inputs import EconomicInputs

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
        puma_map = cache_dir / "comstock" / "geography" / "pumas_northeast.geojson"
        download(comstock.puma_map_url(settings.comstock), puma_map, client)
    puma_by_bldg = dict(zip(meta["bldg_id"].astype(int), meta["puma_gisjoin"], strict=True))
    centroids = puma_centroids(load_geojson(puma_map))
    site_locations(sites, puma_by_bldg, centroids).to_csv(
        settings.resolve(settings.paths.locations_file), index=False
    )
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
def rank(
    dev_subset: bool = typer.Option(False, "--dev-subset", help="Only the 10 dev sites."),
    draws: int | None = typer.Option(None, help="Monte Carlo draws (default from config)."),
    resimulate: bool = typer.Option(False, help="Ignore cached savings and re-simulate."),
    config: Path | None = typer.Option(None, help="Config file (default: config/default.yaml)."),
) -> None:
    """15-year Monte Carlo and robustness ranking, with sensitivity (illustrative)."""
    settings = load_settings(config)
    sites = read_sites(settings.resolve(settings.paths.sites_file))
    sites = [s for s in sites if s.dev_subset] if dev_subset else sites
    assumptions = load_assumptions()
    spec = BatterySpec.from_assumptions(assumptions)

    def simulate_savings() -> pd.DataFrame:
        # Only the sites being ranked, so `fetch-data --dev-subset` + `rank --dev-subset` works.
        tariffs = _tariffs_for(settings, sites, None)
        loads = _cached_loads(settings, sites)
        typer.echo(f"simulating {len(sites)} sites (cached for later runs)...")
        return simulate_sites(sites, loads, tariffs, spec, with_optimal=False)[1]

    savings, was_cached = cached_savings(
        settings, simulate_savings, force=resimulate, site_ids=[s.site_id for s in sites]
    )
    typer.echo(f"savings: {'cache hit' if was_cached else 'simulated'}")
    economics = site_economics(sites, savings, assumptions)
    inputs = EconomicInputs.from_assumptions(assumptions, spec.power_kw)
    n_draws = draws or settings.scenarios.n_draws
    started = time.perf_counter()
    result = rank_sites(economics, inputs, n_draws, settings.scenarios.seed)
    elapsed = time.perf_counter() - started

    out_dir = settings.resolve(settings.paths.cache_dir) / "results"
    result.ranking.to_csv(out_dir / "ranking.csv", index=False)
    result.tornado.to_csv(out_dir / "tornado.csv", index=False)
    result.revenue_sweep.to_csv(out_dir / "revenue_sweep.csv", index=False)
    result.fan.to_csv(out_dir / "fan.csv", index=False, float_format="%.2f")
    pd.DataFrame([vars(s) for s in result.shifts]).to_csv(out_dir / "rank_shifts.csv", index=False)
    meta = {"n_draws": n_draws, "seed": settings.scenarios.seed, "seconds": round(elapsed, 2)}
    (out_dir / "explanations.json").write_text(
        json.dumps({"run": meta, "explanations": result.explanations}, indent=2)
    )
    columns = [
        "rank",
        "site_id",
        "building_type",
        "tariff_is_proxy",
        "npv_p10",
        "npv_p50",
        "npv_p90",
        "p_npv_positive",
        "rank_by_p50",
        "breakeven_capex_usd_per_kw",
        "required_other_revenue_usd_per_kw_year",
    ]
    typer.echo(result.ranking[columns].round(0).to_string(index=False))
    for key, sentence in result.explanations.items():
        typer.echo(f"\n[{key}] {sentence}")
    typer.echo(
        f"\n{len(sites)} sites x {n_draws} draws x {inputs.life_years} years in {elapsed:.1f}s; "
        f"wrote ranking.csv, tornado.csv, rank_shifts.csv to {out_dir} (illustrative)"
    )


def _cached_loads(settings: Settings, sites: list[Site]) -> dict[str, pd.Series]:
    cache = settings.resolve(settings.paths.cache_dir) / "comstock" / "timeseries"
    missing = [s.site_id for s in sites if not (cache / f"{s.bldg_id}.parquet").exists()]
    if missing:
        typer.echo(f"no cached load for {missing}; run `ridgeline fetch-data` first", err=True)
        raise typer.Exit(code=1)
    return {s.site_id: load_cached_timeseries(cache / f"{s.bldg_id}.parquet") for s in sites}


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Interface to bind."),
    port: int = typer.Option(8000, help="Port."),
    config: Path | None = typer.Option(None, help="Config file (default: config/default.yaml)."),
) -> None:
    """Serve the API and the map page at http://HOST:PORT (reads `ridgeline rank` outputs)."""
    import uvicorn

    from ridgeline.api.app import create_app
    from ridgeline.api.data import ApiData, load_api_data

    settings = load_settings(config)
    loaded: list[ApiData] = []

    def provider() -> ApiData:
        # Load lazily and keep the first success; a missing-results error is retried next call,
        # so running `ridgeline rank` while the server is up just works.
        if not loaded:
            loaded.append(load_api_data(settings))
        return loaded[0]

    typer.echo(f"Ridgeline (illustrative) at http://{host}:{port}")
    uvicorn.run(create_app(provider), host=host, port=port)


# ---- M6: agent layer -------------------------------------------------------------------------


def _live_client(settings: Settings) -> AnthropicClient:
    if not has_api_key():
        typer.echo(
            f"{KEY_ENV_VAR} is not set; this command calls the Anthropic API. "
            "Set it in your environment (see .env.example).",
            err=True,
        )
        raise typer.Exit(code=2)
    agent = settings.agent
    model = resolve_model(agent.model)
    typer.echo(f"model: {model} (illustrative; outputs are checked before they are shown)")
    return AnthropicClient(AgentSettings(model, agent.max_tokens, agent.effort))


def _print_checked(errors: list[str], warnings: list[str]) -> None:
    for w in warnings:
        typer.echo(f"  review: {w}")
    for e in errors:
        typer.echo(f"  REJECTED: {e}", err=True)


@app.command()
def evals(
    live: bool = typer.Option(
        False, "--live", help="Score a real model (needs ANTHROPIC_API_KEY)."
    ),
    config: Path | None = typer.Option(None, help="Config file (default: config/default.yaml)."),
) -> None:
    """Run the M6 eval set: offline against the mock client, or live with --live."""
    from ridgeline.agent.evals import load_cases, mock_client, report, run_evals

    settings = load_settings(config)
    cases = load_cases()
    client: LLMClient = _live_client(settings) if live else mock_client(cases)
    if not live:
        typer.echo("offline: mock client with hand-written responses (tests the harness)")
    results = run_evals(client, settings.agent.min_confidence, cases)
    typer.echo(report(results))
    if not all(r.passed for r in results):
        raise typer.Exit(code=1)


@app.command("extract-tariff")
def extract_tariff_cmd(
    path: Path = typer.Argument(
        ..., help="Tariff text file, or a URDB JSON (uses its description)."
    ),
    config: Path | None = typer.Option(None, help="Config file (default: config/default.yaml)."),
) -> None:
    """Extract demand-tariff parameters from text with an LLM, checked against the text."""
    from ridgeline.agent.tariff_extract import extract_tariff

    settings = load_settings(config)
    raw = path.read_text()
    text = str(json.loads(raw)["items"][0]["description"]) if path.suffix == ".json" else raw
    checked = extract_tariff(_live_client(settings), text, settings.agent.min_confidence)
    if checked.output is not None:
        for name, field in checked.output.fields().items():
            shown = "not stated" if field.value is None else f"{field.value}"
            quote = f'  "{field.evidence}"' if field.evidence else ""
            typer.echo(f"{name:<28} {shown:<20} conf {field.confidence:.2f}{quote}")
        for note in checked.output.notes:
            typer.echo(f"note: {note}")
    _print_checked(checked.errors, checked.warnings)
    if not checked.accepted:
        raise typer.Exit(code=1)


@app.command()
def explain(
    site_id: str = typer.Argument(..., help="Site ID, e.g. cs-144167."),
    config: Path | None = typer.Option(None, help="Config file (default: config/default.yaml)."),
) -> None:
    """Explain one site's ranking in plain language with an LLM, grounded in `rank` outputs."""
    from ridgeline.agent.explain import (
        describe_tariff,
        explain_site,
        facts_from_ranking,
        render_facts,
    )

    settings = load_settings(config)
    results = settings.resolve(settings.paths.results_dir)
    if not (results / "ranking.csv").exists():
        typer.echo(f"no ranking.csv in {results}; run `ridgeline rank` first", err=True)
        raise typer.Exit(code=1)
    run = json.loads((results / "explanations.json").read_text())["run"]
    assumptions = load_assumptions()
    inputs = EconomicInputs.from_assumptions(
        assumptions, BatterySpec.from_assumptions(assumptions).power_kw
    )
    try:
        facts = facts_from_ranking(
            pd.read_csv(results / "ranking.csv"),
            site_id,
            tariff_names={t.tariff_id: describe_tariff(t) for t in _load_tariffs(settings)},
            n_draws=int(run["n_draws"]),
            life_years=inputs.life_years,
            capex_usd_per_kw=inputs.capex_usd_per_kw.central,
        )
    except KeyError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from None
    checked = explain_site(_live_client(settings), facts)
    typer.echo("Facts given to the model:\n" + render_facts(facts) + "\n")
    if checked.accepted:
        typer.echo(checked.output)
    _print_checked(checked.errors, checked.warnings)
    if not checked.accepted:
        raise typer.Exit(code=1)
