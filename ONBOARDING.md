# Onboarding

Welcome. After this page you should be able to run Ridgeline, find your way around the code, and
ship one of the starter features at the end. Read `README.md` first for the quickstart.

## 1. The problem in 2 minutes

Commercial electricity bills in Massachusetts include a **demand charge**: a price per kW of the
single highest 15-minute average demand in the month. A behind-the-meter battery can discharge
during those spikes ("peak shaving") and lower the bill.

Whether that pays depends on things we don't know for sure:
- how peaky the building's load is;
- the tariff;
- what the battery costs;
- how it degrades;
- whether the tenant stays for 15 years.

Ridgeline answers: **across 40 candidate buildings, where would a 125 kW / 250 kWh battery be the
most robust investment?** "Robust" means good in bad futures (the 10th-percentile NPV), not just on
average.

It does that in four steps:
1. **Simulate** a realistic controller on each building's real 15-minute load (NREL ComStock) and a
   real demand-charge tariff (MECo G-2), to get one year of bill savings.
2. **Run** a 15-year Monte Carlo over costs, incentives, escalation, degradation, discount rate,
   tenant churn and tariff error.
3. **Rank** sites by P10 NPV, with breakeven battery cost alongside.
4. **Show** what moves the ranking, in plain sentences.

**Today's honest answer:** on demand-charge savings alone, no site pays back at 2026 battery costs.
The ranking tells you where a battery loses least and most reliably, and how much cheaper hardware
or extra revenue it would take (`docs/m4_ranking.md`). Everything is **illustrative**.

## 2. The pipeline

See `docs/architecture.md` for the diagram. Each stage writes files the next reads.

| Step | Command | Reads | Writes | Time |
|---|---|---|---|---|
| 1. Data | `uv run ridgeline fetch-data` | OEDI S3 (ComStock) | `data/sites.csv`, `data/site_locations.csv`, `data/cache/comstock/` | ~30 s |
| 2. Dispatch and bills | (inside `rank`; or `uv run ridgeline simulate --dev-subset`) | cache, `data/tariffs/` | `data/cache/results/savings_*.csv` (fingerprinted) | ~35 s |
| 3. Monte Carlo and ranking | `uv run ridgeline rank` | savings, `assumptions.yaml` | `data/cache/results/ranking.csv`, `fan.csv`, `tornado.csv`, `explanations.json`, ... | ~3 s |
| 4. Report | `uv run python scripts/report_ranking.py` | results | `docs/m4/` (committed) | 2 s |
| 5. Serve | `uv run ridgeline serve` | results, locations, cache | http://127.0.0.1:8000 | — |

`make demo` runs steps 1, 3 and 5.

## 3. Module by module

All code is in `src/ridgeline/`.

| Module | Read this first | What it does | Notes |
|---|---|---|---|
| `config.py`, `config/default.yaml` | `Settings` | Run settings: paths, seeds, selection rules, draws | How to run, never facts about the world |
| `assumptions.py`, `assumptions.yaml` | `Assumption` | Every number about the world, with a source URL or `ASSUMPTION`, optional low/high range | A test fails on any unsourced number |
| `data/schemas.py` | `Site`, `LoadProfile`, `Tariff` | Boundary models, validated once | Downstream code trusts these |
| `data/comstock.py` | `select_sites`, `normalize_timeseries` | Metadata screening, seeded stratified selection, timestamp conversion | ComStock quirks are documented in the docstrings and ADR-003/004 |
| `data/tariffs.py` | `parse_urdb_record`, `match_tariff`, `with_proxies` | URDB JSON to `Tariff`; strict matching; labeled proxies | Refuses what it can't model |
| `data/locations.py` | `site_locations` | PUMA centroid + offset (approximate pins) | |
| `gaps/` | `experiment.py` | Meter-outage simulation and imputation (M2) | Not in the ranking path; current sites have no gaps |
| `battery/` | `simulate.py` | Threshold controller, LP bound, bill calculator, per-month simulation | Property-tested invariants |
| `scenarios/` | `cashflow.py` | One NPV formula, vectorized over sites × draws × years; Monte Carlo sampling | Pure numpy |
| `ranking/` | `pipeline.py` | P10 ranking, breakeven, tornado, sweeps, plain-language sentences | Sentences are generated from numbers |
| `results.py` | `cached_savings` | Fingerprinted cache of simulated savings | See "likely to break" #3 |
| `api/`, `web/` | `api/app.py` | FastAPI over the results files; one Leaflet page | Never recomputes |
| `cli.py` | — | Typer commands wiring it all together | Keep it thin |

## 4. Run, test, debug

```bash
make check
```

```bash
uv run pytest tests/unit/battery -q
```

```bash
uv run ridgeline simulate --dev-subset --tariff-override tests/fixtures/tariff_test_fixture.json
```

- **`make check`** = ruff + `mypy --strict` + pytest. It is offline (committed fixtures only) and
  runs in CI on every push. Run it before every commit.
- **Test layout:** `tests/unit/` mirrors `src/`; `tests/property/` holds hypothesis invariants;
  `tests/golden/` holds the ranking golden file; `tests/e2e/` goes from fixture loads to a ranking.
- **Golden file:** if you *intend* to change ranking numbers, run
  `UPDATE_GOLDEN=1 uv run pytest tests/golden`, review the CSV diff, and say why in the commit.
- **Dev loop:** use `--dev-subset` (10 sites) on `fetch-data`, `simulate` and `rank`.
- **Inspect intermediate files:** `data/cache/results/simulate_monthly.csv` (per-month peaks, bills,
  idle flags), `ranking.csv`, `tornado.csv`, `rank_shifts.csv`.
- **Fake tariff for experiments:** `--tariff-override FILE` applies one tariff to every site;
  outputs are labeled.
- **Stale results:** `rank --resimulate` ignores the savings cache.
- **Logging:** `uv run ridgeline -v fetch-data` shows download logging.

## 5. The five places most likely to break

1. **Timestamps and daylight saving** (`data/timestamps.py`, ADR-003). ComStock stamps are local
   *standard* time and interval-*ending*; tariffs are wall-clock time. A one-hour slip moves every
   on-peak window for seven months and nothing crashes. `tests/unit/test_timestamps.py` pins this
   on real data. Any new data source needs the same check.
2. **Tariff files** (`data/tariffs.py`, ADR-005/009/010). URDB records vary:
   - multi-URL `source` fields (this already bit us once);
   - kVA demand, tiers, ratchets;
   - `approved: false` records.
   Every committed tariff should get a data-contract test like
   `test_committed_meco_g2_matches_its_published_values`. Matching fails loudly on zero or two
   matches, so read that error and don't work around it.
3. **The savings cache** (`results.py`). It is keyed on the site list, tariff files, proxy rules,
   battery assumptions, and `battery/`, `data/tariffs.py` and `data/schemas.py` source. If you make
   savings depend on anything else (a new module, a new config value), add it to
   `savings_fingerprint`, or `rank` will silently reuse stale numbers.
4. **Monte Carlo noise vs rank precision** (`ranking/`, ADR-011). The 40 sites sit a few hundred
   dollars apart, so ranks within ~4 places are ties at 8,000 draws. If you change draws, inputs or
   sites, look at the `rank_stability` sentence before believing a rank change. Scenario
   comparisons share random draws on purpose; keep it that way.
5. **External data and services.** These can all move or change under us:
   - the OEDI paths for ComStock release 2 (`config/default.yaml`);
   - the URDB record;
   - the Leaflet CDN and OpenStreetMap tiles used by the page (not by tests).

   If `fetch-data` 404s, check the release path first. CI never touches the network, so it won't warn you.

## 6. Three starter features

Each one is scoped to a few files, has an obvious test, and moves the main result.

### A. Better threshold forecasting (biggest lever on viability)

- **Why:** the practical controller captures a median ~51% of the perfect-foresight savings. With
  perfect foresight, 9 of the 10 dev sites would cover O&M (M3, M4 caveats).
- **Where:**
  - add a forecaster in `battery/dispatch.py`, for example "previous month's threshold scaled by a
    weather-driven expected peak" or "same month last year" once there is more than one year of data;
  - wire it into `battery/simulate.py`, where `start_threshold` is set;
  - keep the causal rule: no information from the month being simulated.
- **Test:** the existing property tests (SoC, conservation, never raising the peak) must still
  pass. Add a dev-subset check that median capture rises, and report it like the lookahead comparison
  in `docs/m3_dispatch.md`.

### B. A proper MECo G-3 tariff for sites above 200 kW

- **Why:** 23 of 40 sites use G-2 values as a labeled proxy (ADR-010).
- **Where:**
  - drop the URDB JSON into `data/tariffs/`;
  - add a data-contract test in `tests/unit/test_tariffs.py`;
  - remove or narrow the proxy rule in `config/default.yaml`.
- **Watch out:** billing already supports TOU demand charges, but the practical controller only
  defends the all-hours peak (LIMITATIONS.md), so check how much of the LP's advantage is TOU windows.
- **Done when:** `rank` shows `tariff_is_proxy = false` for those sites, `docs/m4` is regenerated,
  and the proxy-sweep sentence is updated.

### C. A revenue-stacking scenario

- **Why:** real projects stack demand-response payments. Today the model reports the *required*
  other revenue ($124–160/kW-year) instead of assuming any (ADR-012).
- **Where:**
  - add an `other_revenue_usd_per_kw_year` term to `scenarios/cashflow.py` (a `Draws` field, so it
    can be uncertain);
  - add an `assumptions.yaml` entry **with a source URL for the program's published rate**, or
    `ASSUMPTION` with a range;
  - add a column through `ranking/` and `api/models.py`.
- **Test:** hand-computed NPV with revenue, plus the property that more revenue never lowers NPV.
  Golden file updated deliberately.

## 7. House rules

- **No unsourced numbers.** Every number about the world goes in `assumptions.yaml` with a source
  URL or `ASSUMPTION`.
- **Uncertainty is shown, not hidden.** Report intervals (P10/P50/P90), not point estimates.
- **Decisions get an ADR** in `DECISIONS.md`: context, decision, rejected alternatives.
- **Simplifications go in `LIMITATIONS.md`,** in plain words.
- **AI-assisted work goes in `AI_LOG.md`:** what was generated, what was wrong, and how it was caught.
- **Small typed commits**, each passing `make check`; a regression test for every bug fixed.
