# Ridgeline: handoff for the next session

Last updated 2026-11-09. This file is for whoever (human or AI) continues the project. It has
everything needed: the original brief, every decision and preference made so far, the exact repo
state, results, gotchas, and what is left. Read it top to bottom once. After that, `ONBOARDING.md`
(how the code works) and `DECISIONS.md` (why) are the deeper references.

---

## 0. TL;DR

- **What:** Ridgeline ranks 40 Massachusetts commercial buildings for behind-the-meter battery
  peak shaving (125 kW / 250 kWh) by **robustness under uncertainty** (P10 NPV), not by expected
  value. Personal portfolio project, walked through with an interviewer. All outputs are
  **illustrative**.
- **Repo:** https://github.com/Lkumar209/Ridgeline (owner `Lkumar209`, the user Laxya Kumar).
- **Done:** M0–M7, plus follow-ups and download retries. CI is green.
- **M6 (LLM agent layer) is built and tested offline** (mock client, 11 evals, ADR-014). Its live
  path has **not** been run: no `ANTHROPIC_API_KEY` was available. First live step: set the key and
  run `uv run ridgeline evals --live`.
- **Open PR:** **#5**. It holds the clarity fixes, this handoff, download retries and M6, all on
  branch `claude/dazzling-cori-pty3ol`, waiting for the user to merge.
- **Headline finding:** on demand-charge savings alone, no site pays back at NREL ATB 2026
  battery costs (~$1,570/kW). Only cs-118913 would break even in the central case, at a hypothetical
  ~$56/kW battery. The other 39 never pay back, even at $0 battery cost (savings < fixed O&M ~$4.7k/yr).
- **Quickstart:** `git clone … && cd Ridgeline`, then `uv sync`, then `make demo` (fetch ~30 s,
  rank ~35 s first time, then serves http://127.0.0.1:8000). `make check` is offline: 232 tests,
  ruff, `mypy --strict`. `make evals` runs the M6 evals offline.

### Suggested opening message for the next chat

> Read HANDOFF.md, ONBOARDING.md and DECISIONS.md in the Ridgeline repo. Check whether PR #5 is
> merged. Then [run the M6 live evals with my key / do X]. Follow the working rules in HANDOFF.md section 3.

---

## 1. The original brief (condensed but complete)

The user's brief, kept here because the next session will not have the original chat.

### Goal
Rank commercial sites in Massachusetts for behind-the-meter battery peak shaving:
- For each site, simulate a battery (default **125 kW / 250 kWh**, configurable) against the
  site's load curve and a **real commercial tariff with demand charges**.
- Run a **15-year Monte Carlo** cash-flow model under uncertainty.
- Rank by **robustness**, not just expected value.

It is inspired by a startup's problem, not a replica of anyone's model, so label all outputs
illustrative. The interviewer judges turning ideas into code, system design, code quality and
communication. A new teammate must be able to add a feature after reading README + ONBOARDING.

### Non-negotiable principles
1. **Every milestone ends working, tested and committed.** Never break `main`.
2. **Honest data.** Use real data where it exists and clearly label synthetic data. Never invent
   tariff values, incentive amounts or costs and present them as real. Every assumption goes in
   `assumptions.yaml` with a **source URL or the label "ASSUMPTION"**.
3. **Uncertainty is first-class.** No point estimates without intervals in anything user-facing.
4. **Audit AI output.** Keep `AI_LOG.md` per milestone: key prompts, what was generated, what was
   wrong or rejected, and how a test or check caught it.
5. **Small, typed, readable code.** Python 3.11+, `uv`, pytest, ruff, mypy (strict), pydantic at
   module boundaries, no giant functions, pure functions for the simulation core.
6. **Simple, explainable methods.** Justify every dependency.

### Environment rules (from the brief)
- Work in the connected GitHub repo, open a PR per milestone for the user to review, and never push to `main`.
- If network access blocks a download or API, **say which domain is blocked and stop**. Don't
  silently switch to synthetic data.
- **Keys:** read from env vars only: `URDB_API_KEY` (OpenEI/NREL) and `ANTHROPIC_API_KEY`. Never
  hardcode, commit or print them. `.env.example` lists names only (it exists).
- Cache large data under `data/cache/` (gitignored). Keep the repo small.

### Architecture (modules under `src/ridgeline/`)
`data/`, `gaps/`, `battery/`, `scenarios/`, `ranking/`, `agent/` (M6), `api/`, `web/`, `cli.py`
with commands `fetch-data`, `simulate`, `rank`, `serve`. All exist; M6 added `evals`,
`extract-tariff` and `explain`.

### Milestones (in order; ask before skipping or reordering)
- **M0** data feasibility spike (ComStock on OEDI S3; URDB API). **Done.**
- **M1** scaffold, config, schemas, `make check`, 20–50 cached sites. **Done.**
- **M2** gap injection and imputation, validated on billing-peak error. **Done.**
- **M3** threshold controller, bill calculator, perfect-foresight LP bound, property tests. **Done.**
- **M4** 15-yr Monte Carlo, P10/P50/P90, P(NPV>0), robustness score, tornado, churn. **Done.**
- **M5** API and map UI. **Done.**
- **M6** agent layer with the Anthropic SDK. **Done offline** (live path untested; no key); §9.
- **M7** hardening and docs: fresh-clone test, README, ONBOARDING, architecture diagram,
  limitations. **Done.**

### Testing bar
- Unit tests for every pure function.
- Hypothesis property tests for battery and billing.
- A golden-file test for ranking.
- At least one end-to-end test from fixture to ranking.
- A regression test for every bug fixed.
- `make check` passes before each commit.

All of this is met.

### Docs deliverables
`README.md`, `ONBOARDING.md` (with the 5 places most likely to break and 3 starter features),
`DECISIONS.md` (ADRs), `LIMITATIONS.md`, `AI_LOG.md`. All exist and are current.

### Working style
- Plan first, and per milestone state the approach and acceptance criteria.
- Ask short questions when the decision is the user's.
- Don't add features beyond the brief; list improvements as future work.
- After each milestone, give a **5-line summary**: what works, what's tested, what's weak, what's next.

---

## 2. Current repo and GitHub state

| Item | State |
|---|---|
| `main` | `8ac1fcf` (merge of PR #4). Contains M0–M5 + M7 + the M4 follow-up. |
| Working branch | `claude/dazzling-cori-pty3ol`. All commits pushed; local == remote. |
| PR #1 | M0–M2. Merged. |
| PR #2 | M3. Merged. |
| PR #3 | M4 (+ CI workflow, M2 refresh). Merged. |
| PR #4 | M4 follow-up + M5 + M7. Merged. |
| **PR #5** | **Open.** Clarity fixes (`75a6730`, `14dca5f`), HANDOFF.md, download retries, M6. |
| CI | `.github/workflows/check.yml`: `uv sync --locked` then `make check` on every push and PR. Offline. Green. |
| Tests | 232 (unit, property, golden, e2e, api, agent). |
| Tracked files | ~125. Code is ~3,700 lines of Python in `src/`. |

**Download retries** now exist (ADR-015): `data/cache.py` retries connection errors, timeouts,
429 and 5xx (4 attempts; 2, 4, 8 s), and fails at once on other 4xx. The earlier
"download-retry PR" the user asked about never existed; this was built afterwards.

---

## 3. Working rules and user preferences (follow these)

### Git, authorship and PRs
- **Commit author is the user,** not Claude: `Laxya Kumar <112336121+Lkumar209@users.noreply.github.com>`.
  Set it with `git config user.name/user.email` in the repo; the container default is "Claude".
- **No `Co-Authored-By: Claude` trailer** and **no `Claude-Session` trailer** in commits. The user
  asked to "remove claude as contributor". The PR-description footer ("Generated with Claude Code")
  is fine; the user said to leave it.
- **Two old commits still show Claude as author:** the bootstrap commit `6817817` and the M0 commit
  `b8fc8ee`. Rewriting them needs a force-push to `main`. The permission guard blocked it, and the
  user said to leave history as is. **Don't rewrite history.**
- **Branch workflow** (ADR-006): the cloud session could only push its one session branch. One PR
  per milestone into `main`. After a merge, restart the branch from `origin/main`
  (`git checkout -B <branch> origin/main`; it fast-forwards because PRs are merge commits).
  If a new session has a different branch name, use that one.
- **Commit hygiene:**
  - Small commits, each passing `make check`.
  - **Gate commits on make's real exit code**
    (`make check > log 2>&1; rc=$?; [ $rc -eq 0 ] && git commit …`). Never pipe make's output into
    grep before `&&`: it once let a failing commit through.
  - Verify each commit in a clean worktree before pushing a batch.
- **When editing files with scripted `str.replace`, assert the match.** A silent no-op once left a
  wrong header in place.

### PR monitoring preference
- **Watch PRs for CI failures only.** Leave review comments to the user.
- Subscribe after opening a PR. Use one safety-net check-in about 50 min later, and stop if nothing
  has changed.

### Communication preferences
- **End each milestone with a 5-line summary** (what works / tested / weak / next / open items).
- **Plain-language sentences for non-experts.** M4 requires one generated sentence per sensitivity
  result. Words like "substantially" or "barely" must come from the numbers, never be hard-coded.
- **Never say "the best site" ambiguously.** Name the site and say by which measure (P10 rank vs
  median vs breakeven).
- **Negative breakeven** is shown as "never pays back, even at $0 battery cost", never "-$27/kW".
  Use `ranking.pipeline.breakeven_label()`.
- **Report problems honestly.** If a request references something that doesn't exist (like the
  retry PR, or a JSON "attached" without content), say so; never fabricate it.
- **Data the user sends** (tariff JSON etc.) is saved **verbatim**, validated, and pinned with a
  data-contract test.

---

## 4. Environment facts (cloud session)

- **Network:** the proxy **blocked** `api.openei.org` (URDB API), `developer.nrel.gov`, `eia.gov`,
  `www2.census.gov`, `unpkg.com`, `tile.openstreetmap.org`, `nationalgridus.com`, `eversource.com`.
  It **allowed** `oedi-data-lake.s3.amazonaws.com` (ComStock and NREL ATB), PyPI,
  `registry.npmjs.org`, GitHub and `api.anthropic.com`.
- **Keys:** `URDB_API_KEY` and `ANTHROPIC_API_KEY` were **not set** in this environment.
  `ANTHROPIC_BASE_URL` was set. For a live M6 run, the user must provide the key, via the
  environment's credential feature, not chat.
- **Map page tiles and Leaflet** load from the internet in the user's browser (that works on their
  Mac). For headless screenshots here, Leaflet 1.9.4 was fetched from the npm registry into scratch
  and the CDN URL was routed to it in Playwright. Tiles stay blank in the sandbox.
- **Python** 3.11 via uv (`.python-version`). Chromium and Playwright are preinstalled in the
  container (`require('playwright')`). The Mermaid CLI was installed into scratch only.

---

## 5. What was built: milestone by milestone

### M0: data feasibility (`spikes/m0_data_feasibility.md`, `spikes/m0_probe.py`)
- **ComStock 2024 release 2** (AMY2018), `upgrade=0`, on OEDI S3: works without a key. It has MA
  metadata (per county), 15-min per-building parquet files (3,595 MA files, 15.4 GB in total; we
  cache a few MB), and hourly county weather.
- **URDB API blocked** (`api.openei.org`), so the tariff came as a user-supplied URDB JSON.
- **Gotchas found:**
  - Metadata rows are building × tract allocations; dedupe on `bldg_id`.
  - About a third of buildings were "as simulated" in Connecticut; filter them out.
  - The "basic" metadata file lacks the peak and utility columns; use "full".
  - There are no coordinates.

### M1: scaffold and data layer
- uv, ruff, `mypy --strict` (whole package), pytest + hypothesis, `make check`.
- **Schemas** (`data/schemas.py`): `Site`, `LoadProfile`, `TouSchedule`, `Tariff`, `BatterySpec`.
- **Assumptions validator** (`assumptions.py`): each entry needs a source URL or `ASSUMPTION`, plus
  optional `low`/`high` (validated `low <= value <= high`).
- **Timestamp convention (ADR-003):**
  - ComStock stamps are **local standard time (UTC-5) all year, interval-ending**, while building
    schedules follow DST.
  - We convert once to UTC interval-start and apply tariffs in `America/New_York`.
  - Proven on real data: lighting schedules align on wall-clock time in Feb vs Jul only after
    conversion (test).
- **Site selection (ADR-004):**
  - 40 sites = 8 types × 5: MediumOffice, RetailStripmall, RetailStandalone, PrimarySchool,
    SecondarySchool, Outpatient, Warehouse, FullServiceRestaurant.
  - Peak 100–1,000 kW.
  - Per type, 2/1/2 sites from the low/mid/high peak-to-average (PAR) terciles. Low-PAR sites are
    included on purpose for spread.
  - Seed `20261102`, MA-simulated only.
  - Counties: Middlesex, Worcester, Suffolk, Hampden.
  - Utilities 11804 + 54913. The first 10 sites in order are the **dev subset**.
- `data/sites.csv` is committed and regenerated byte-identically by `fetch-data`.

### M2: gap imputation (`docs/m2_imputation.md`)
- **Setup:** 240 seeded outages (30–92 days) on all 40 sites.
- **Methods:**
  - seasonal-profile baseline;
  - **ridge regression** (weekday/weekend × 15-min slot dummies + degree terms): the default;
  - regression + peer-site signal.
- **Results on the current site list:**

  | Method | Billing-peak abs error (median) | Bias | MAPE |
  |---|---|---|---|
  | Baseline | 13.3% | −14.3% | 16.0% |
  | Regression | 7.3% | −3.4% | 16.1% |
  | + peers | 5.3% | −1.1% | 13.9% |

- **Lessons:**
  - MAPE can't tell the methods apart, but billing-peak error can.
  - Peers are not the default, because ComStock's shared prototype schedules flatter them (ADR-007).
  - Hourly vs 15-min dummies is a bias-vs-spread trade-off (documented).

### M3: dispatch and billing (`docs/m3_dispatch.md`)
- **Billing** (`battery/billing.py`): energy, flat demand, TOU demand and fixed charges per local
  calendar month. A golden bill is hand-computed.
- **Practical controller** (`battery/dispatch.py`): threshold rule with a ratchet. The starting
  threshold is the lowest the battery could have held **last month** (causal). **The first month is
  idle** (no history).
  - The old January←December wraparound was a lookahead. It was removed and is now only
    `--wraparound-lookahead`. Median capture went 0.565 → 0.544 because of it.
- **Upper bound** (`battery/optimal.py`): LP per month (scipy HiGHS, sparse).
- **Oracle-threshold diagnostic.** With the right threshold, the rule matches the LP's peak cut and
  ~97% of its savings, so **the gap is forecasting, not the rule**.
- **Idle guard:** a month that would cost more than no battery is billed idle.
- **Property tests:**
  - SoC bounds and power limits;
  - energy conservation with losses;
  - no export;
  - the battery never raises the billing peak;
  - bill with battery ≤ bill without;
  - LP bill ≤ every controller's bill.
- **Tariff** (`data/tariffs/meco_g2_sema.json`): **MECo G-2 Demand SEMA**, URDB
  `67d08dea7568c8189f03c54e`, EIA 11804, committed verbatim.
  - **Rates:** $14.82/kW flat demand (all months), $0.0733/kWh delivery, $45/month fixed.
  - **Eligibility:** max 200 kW (`peakkwcapacitymax`), average use ≥ 10,000 kWh/month
    (`peakkwhusagemin`). The user confirmed the **average-month** reading.
  - **Record caveats:** `approved: false`, servicetype Delivery (supply excluded).
  - **kVA clause** (90% of kVA above 75 kW): simplified to the kW peak (ASSUMPTION); equal at PF 0.90.
  - A data-contract test pins all of this.
- **Loader** (`data/tariffs.py`):
  - URDB v8 JSON; refuses tiers, $/day fixed charges, unknown units and mixed kW/kVA.
  - $/kVA → $/kW via `power_factor_for_kva_demand` (0.90, ASSUMPTION).
  - Strict matching (`TariffMatchError` on 0 or 2+ matches).
  - Bug fixed: multi-URL `source` fields were being glued into one URL; sources are now a list.
- **Coverage decision (ADR-010):**
  - Sites above 200 kW on EIA 11804 are billed on **G-2 values as a labeled proxy** (config
    `tariff_proxies`, assumption `g2_proxy_above_200kw`, output flag `tariff_is_proxy`).
  - The 5 NSTAR (54913) sites were **replaced** by same-type, same-tier 11804 sites; the other 35
    are byte-identical.
  - Coverage is now **17 real G-2 + 23 proxy** (dev subset: 6 + 4).
- **Dev-subset results on real G-2** (delivery bills only):
  - practical savings $1.6k–$6.4k/yr;
  - LP bound $4.6k–$12.9k/yr;
  - median capture 0.51;
  - 6 of 120 site-months idle.

### M4: Monte Carlo and ranking (`docs/m4_ranking.md`, generated `docs/m4/results.md`)
- **Inputs:** practical-controller year-1 savings split into **demand** and **energy** parts
  (cached under a fingerprint, `results.py`).
- **NPV formula** (`scenarios/cashflow.py`), per site × draw × year (one vectorized function):
  `npv = sum(discounted_cashflows)`.
  - Year 0 = −capex × (1 − incentive).
  - Years 1–15 = (alive × savings − O&M) / (1 + r)^t.
  - savings = (m_proxy × demand + energy) × escalation^(t−1) × (1 − fade)^(t−1) × noise.
- **Churn:** when the tenant leaves, **savings stop and O&M continues** (the battery stays with the
  building). This was fixed after the first version had churn *raising* NPV.
- **Sampling:** shared global draws across sites; per-site noise and churn seeded by
  `(seed, bldg_id)`; churn via inverse-CDF of fixed uniforms, so scenarios compare like with like.
  **8,000 draws** (seed 2026).
- **Ranking** (`ranking/metrics.py`):
  - **robustness score = P10 NPV**;
  - also P50 rank, P(NPV>0);
  - **breakeven capex ($/kW)**, the main companion metric;
  - **other revenue needed ($/kW-yr)** (ADR-012).
- **Sensitivity** (`ranking/sensitivity.py`, `pipeline.py`):
  - tornado;
  - proxy demand charge pinned at ×0.7/×1.3 (proxy sites only), with an all-sites contrast;
  - churn on/off;
  - second-seed stability;
  - a site counts as "moved" only if it shifts more places than seed noise (now 5+).
- **Key numbers** (all illustrative, 2025$):
  - **Viability:** 1 of 40 sites has NPV > 0 in 1 of 8,000 draws.
  - **Most robust:** cs-144167 (SecondarySchool, proxy). P10/P50/P90 = −$217,153 / −$171,180 /
    −$131,541; never pays back even at $0.
  - **Closest to breakeven:** cs-118913 (RetailStripmall, best by median, 6th on P10): ~$56/kW.
    The other 39 never pay back.
  - **Capex and O&M:** central $1,570/kW in 2025$ (ATB $1,427.61 × 1.10) = ~$196k for 125 kW;
    O&M ~$4.73k/yr.
  - **Other revenue needed:** min $124 (cs-118913), median $147, max ~$160 /kW-yr. At $150: 13
    likely / 0 robust viable; at $200: 40 likely / 31 robust.
  - **Tornado:** capex ($78k swing), incentive ($59k) and O&M ($23k) move **0 ranks** (same battery
    everywhere). Churn moves 15 sites and the proxy demand charge 26 (5+ places).
  - **Scenarios:**
    - proxy ×0.7: 15 moved, top-10 kept 7;
    - proxy ×1.3: 9 moved, kept 8;
    - all-sites ×0.7/×1.3: 1/0 moved;
    - churn off: 24 moved, kept 3; churn lowers P10 by ~$13,671.
  - **Precision:** neighbors differ by a median $329 at P10, and the seed moves sites up to 4
    places, so treat ±4 as ties.
  - **By type** (median rank): SecondarySchool 5, Outpatient 9, PrimarySchool 17, MediumOffice 19,
    RetailStripmall 21, RetailStandalone 23, Warehouse 27, FullServiceRestaurant 38.
- **Runtime:** Monte Carlo + all sensitivity ~3 s; savings simulation ~35 s for 40 sites (cached);
  fresh clone fetch + rank 96 s.

### M5: API and map (`src/ridgeline/api/`, `src/ridgeline/web/`)
- **Server:** `ridgeline serve` (FastAPI + uvicorn) **reads only rank outputs** and never recomputes.
- **Endpoints:**
  - `/api/health`;
  - `/api/sites` (rank order, approximate location, `breakeven_label`);
  - `/api/rankings` (rows, explanations, revenue sweep);
  - `/api/sites/{id}` (daily load curve and 15-yr cash-flow fan);
  - 404 for an unknown site; 503 with "run `ridgeline rank`" if results are missing.
  - `create_app(provider)` takes an injectable data provider, so tests are offline.
- **Page:** one static page, vanilla JS + hand-written SVG; Leaflet 1.9.4 from unpkg with SRI.
  - Pins in 5 rank groups (validated ordinal blue ramp).
  - Clicking a pin shows stats and the load and fan charts.
  - Explanations sit under the map on desktop (PR #5).
- **Locations:** ComStock has none, so each pin is the **PUMA centroid** (ComStock's own PUMA
  GeoJSON) + a deterministic ~1 km offset, labeled approximate. Stored in `data/site_locations.csv`.

### M7: docs and hardening
- README (3-command quickstart), ONBOARDING.md, `docs/architecture.md` (Mermaid, rendered locally
  to confirm), ADR-013.
- **Fresh-clone test passed:**
  - 181/175 tests passed at the time;
  - the site files regenerated identically;
  - `ranking.csv` was byte-identical to `docs/m4/ranking.csv`.

### Follow-ups after M5 (PR #5)
- "Never pays back, even at $0 battery cost" wording (one function, served by the API).
- The headline and revenue sentence name the site meant.
- Layout tightened.

---

## 6. Repo map (where things are)

```
src/ridgeline/
  config.py            Settings from config/default.yaml (paths, seeds, selection, gaps, proxies, scenarios)
  assumptions.py       assumptions.yaml loader; source-or-ASSUMPTION rule; low/high ranges
  cli.py               typer: fetch-data, simulate, rank, serve
  results.py           fingerprinted savings cache (sites, tariffs, proxies, battery assumptions,
                       battery/ + data/tariffs.py + data/schemas.py source)
  data/                schemas, comstock (select/normalize/fetch), tariffs (parse/match/proxies),
                       timestamps, weather, sites, locations (PUMA centroids), cache (download)
  gaps/                inject, features, impute_baseline, impute_model, evaluate, experiment (M2)
  battery/             model, dispatch (threshold), optimal (LP), billing, simulate (M3)
  scenarios/           inputs (EconomicInputs, SiteEconomics), cashflow, montecarlo (M4)
  ranking/             metrics, sensitivity, pipeline (rank_sites, sentences, breakeven_label)
  api/                 app (create_app), data (load_api_data), models (pydantic responses)
  web/                 index.html, styles.css, app.js
config/default.yaml    run settings
assumptions.yaml       every number about the world (30 entries)
data/sites.csv         the 40 sites (committed); data/site_locations.csv (approx pins)
data/tariffs/          meco_g2_sema.json + README (format and rules)
data/fixtures/         real ComStock sample rows + weather (offline tests)
tests/                 unit/ (incl. api/, battery/, gaps/, scenarios/), property/, golden/, e2e/
                       fixtures/tariff_test_fixture.json = FAKE tariff (labeled), for tests only
scripts/               build_fixtures, evaluate_imputation, plot_imputation, report_ranking
docs/                  architecture.md, m2_imputation.md (+m2/), m3_dispatch.md (+m3/),
                       m4_ranking.md (+m4/ generated), m5/map_page.png
spikes/                M0 report and probe
.github/workflows/check.yml   CI
```

`config/default.yaml` key values:
- **site_selection:** seed 20261102; peak 100–1000 kW; `par_tier_quota` 2/1/2; utilities
  [11804, 54913] with 54913 replaced.
- **gaps:** seed 7; 6 gaps per site of 30–92 days; window 28 days; hinges 18/10 °C; ridge 1.0.
- **scenarios:** seed 2026; 8,000 draws.
- **tariff_proxies:** G-2 → 11804 above 200 kW.

`assumptions.yaml` keys:
- **Battery:** `battery_power_kw`, `battery_energy_kwh`, `battery_round_trip_efficiency` (0.88),
  `battery_soc_min` (0.05), `battery_soc_max` (0.95).
- **Tariff handling:** `power_factor_for_kva_demand` (0.90), `billing_demand_basis`,
  `bill_scope_delivery_only`, `g2_proxy_above_200kw`, `meco_g2_urdb_record`.
- **Data:** `comstock_load_data`.
- **Costs (sourced, NREL ATB 2024 v3 on OEDI):** `battery_capex_usd_per_kw` (1427.61,
  range 1118.26–1784.03) and `battery_fixed_om_usd_per_kw_year` (34.40, range 26.95–42.99).
- **Economic ASSUMPTIONs:** `usd_2022_to_2025_factor` (1.10), `discount_rate_real` (5%, 3–8%),
  `tariff_escalation_real` (0, −1 to +2%), `upfront_incentive_fraction` (15%, 0–30%; capex-reducing
  only, NOT ConnectedSolutions-type payments), `capacity_fade_per_year` (2%, 1–3%),
  `proxy_demand_charge_multiplier` (1.0, 0.7–1.3), `annual_savings_noise_sd` (0.10),
  `project_life_years` (15), `tenant_churn_multiplier` (1, 0.5–2).
- **Churn hazards (ASSUMPTION):** `tenant_churn_hazard_<Type>` per type: offices 6%, strip malls
  10%, standalone retail 8%, restaurants 12%, warehouses 6%, outpatient 4%, schools 1%.

---

## 7. Commands, tests, workflows

```bash
uv sync
```
```bash
make check          # ruff check + ruff format --check + mypy (strict) + pytest -m "not network"
```
```bash
make demo           # fetch + rank + serve (http://127.0.0.1:8000)
```

- **Fetch:** `uv run ridgeline fetch-data [--dev-subset]` writes `data/sites.csv`,
  `data/site_locations.csv` and the cache (ComStock timeseries, weather, PUMA map).
- **Simulate:** `uv run ridgeline simulate [--dev-subset] [--tariff-override tests/fixtures/tariff_test_fixture.json] [--no-optimal] [--wraparound-lookahead]`.
  Exits 1 and lists every site without exactly one tariff.
- **Rank:** `uv run ridgeline rank [--dev-subset] [--draws N] [--resimulate]` writes
  `data/cache/results/{ranking,fan,tornado,rank_shifts,revenue_sweep}.csv` and `explanations.json`.
  A cache miss and a cache hit are byte-identical.
- **Report:** `uv run python scripts/report_ranking.py` regenerates `docs/m4/` from the latest rank.
  Re-run it after any change that affects ranking numbers or wording, and commit the result.
- **M2 experiment:** `uv run python scripts/evaluate_imputation.py && uv run python scripts/plot_imputation.py`
  (~65 s) regenerates `docs/m2/`.
- **Golden file:** `UPDATE_GOLDEN=1 uv run pytest tests/golden` only when ranking numbers are meant
  to change. Explain why in the commit.
- **Verifying the page:** start `serve`, then use Playwright (see §4 for the CDN routing trick).
  Stop the server by port (`fuser -k 8765/tcp`), **not** `pkill -f "ridgeline serve"`: that killed
  its own shell.

---

## 8. Open items and remaining work (prioritized)

1. **Merge PR #5** (user action), then restart the branch from `origin/main`.
2. **M6 live check** (built; see §9). Needs the user's `ANTHROPIC_API_KEY`. Run
   `uv run ridgeline evals --live`, fix prompts if cases fail, and record results in AI_LOG.
3. **A real MECo G-3 tariff for sites above 200 kW** (the user was searching). When it arrives:
   - save it verbatim to `data/tariffs/`;
   - add a data-contract test like `test_committed_meco_g2_matches_its_published_values`;
   - remove or narrow the `tariff_proxies` rule;
   - re-run `rank` and `report_ranking.py`, and update docs (ADR-010, LIMITATIONS, README, M4 doc).
   - G-3 is TOU, and the practical controller only defends the all-hours peak (LIMITATIONS), so
     check how much of the LP advantage is TOU windows.
4. **ONBOARDING starter features** (well scoped):
   - **A. Better threshold forecasting:** the biggest lever. With perfect foresight, 9 of the 10 dev
     sites would cover O&M.
   - **B. G-3 tariff:** as item 3.
   - **C. A revenue-stacking scenario:** add a sourced or ASSUMPTION `other_revenue` term to
     `Draws`; never a guessed amount presented as real.
5. **Download retry: done** (ADR-015). The policy (4 attempts, 2/4/8 s, transient errors only)
   was chosen without asking; change `ATTEMPTS`/`BACKOFF_S` in `data/cache.py` if the user wants
   another.
6. **Docs to refresh after any of the above:** README "Status", AI_LOG
   (new entry per milestone), DECISIONS (new ADR), LIMITATIONS, and `docs/m4/` (regenerated).

**Future work noted but not requested** (don't build unless asked):
- multi-year load data (to remove the idle first month);
- carrying SoC across months;
- propagating M2 imputation error into M4 for real meter data;
- supply-side energy costs;
- per-program incentive modeling with sources;
- real-world validation of the peer imputer;
- vendoring Leaflet for fully offline use.

---

## 9. M6 spec (from the brief) and the design that was built

**Status:** built as described below (ADR-014; LIMITATIONS "LLM agent layer"; AI_LOG "M6"). Where
the build differs from this plan: one `LLMRequest` (system, user, optional JSON schema) instead of
messages/tools; `numbers.py` holds the number matching; evals live in
`src/ridgeline/agent/evals/` and run with `ridgeline evals` / `make evals`; no API endpoint.

**Brief:** an agent layer using the Anthropic SDK, with the model name from config/env, and two
functions:
1. **Extract tariff parameters** from a tariff description or document text into a pydantic
   schema. Return **per-field confidence** and **refuse to guess missing fields**.
2. **Explain a site's ranking** in plain language, **grounded only in the numbers provided**.

Also required:
- an **eval set of 10+ cases** with expected outputs;
- a **deterministic mock client** so tests run offline;
- a **validator that rejects outputs inconsistent with the source text**.

**Suggested design** (consistent with the codebase):
- **Layout:** `src/ridgeline/agent/` with `client.py`, `tariff_extract.py`, `explain.py`,
  `validators.py`, `evals/`.
- **`client.py`:** an `LLMClient` Protocol (`complete(system, messages, tools?) -> str/JSON`).
  - `AnthropicClient` reads `ANTHROPIC_API_KEY` and `RIDGELINE_LLM_MODEL` from env. Never log the
    key. Add `anthropic` as a dependency, justified in an ADR.
  - `MockClient` returns canned responses keyed by input hash, for offline tests.
  - **Before writing SDK code, load the `claude-api` skill** for current model IDs and API usage.
    The model ID comes from config/env, not hardcoded.
- **Tariff extraction:**
  - **Output schema:** each field (utility, name, flat demand $/kW by month, energy rates, fixed
    charge, kW/kWh eligibility, demand unit, servicetype) is
    `{value | null, confidence 0–1, evidence: exact quoted span}`.
  - **Missing fields must be null**, with "not stated" as the evidence.
  - Use structured output (tool use / JSON schema).
  - **Validator:** every non-null value's `evidence` must appear verbatim in the source text, and
    the number in the evidence must equal the value. Reject otherwise.
  - Can map the result into the existing `Tariff` model or URDB JSON.
  - **Good eval source:** the committed G-2 record's `description` text and its known values
    ($14.82, 200 kW, 10,000 kWh, the 90% kVA clause, 5 kW floor), plus synthetic snippets that omit
    fields (the expected result is null, not a guess).
- **Explanation:**
  - **Input:** one site's ranking row, fan, tornado-relevant facts and the explanation sentences
    (the API data).
  - **Output:** a short paragraph.
  - **Validator:** every number in the output must appear in the input (after formatting
    normalization); refer to sites by ID; no "the best site" without a measure. Reject unsupported
    claims.
- **Evals:**
  - `evals/cases.yaml`, 10+ cases: 5+ extraction (including missing-field and conflicting-text
    cases) and 5+ explanation (including a site that "never pays back", proxy vs real tariff, and
    a site whose rank differs by P10 vs median).
  - `make evals` runs them against the mock by default and live with a key.
- **CLI (optional):** `ridgeline explain <site_id>`. Possibly an API endpoint, but keep M6 minimal
  and ask.
- **Docs:** ADR-014; LIMITATIONS (LLM limits); AI_LOG entry; README status; ONBOARDING module row.

---

## 10. Lessons learned and gotchas (from AI_LOG; avoid repeating them)

- **pandas 3** indexes may be in s/ms/us, not ns. Never use `asi8 // 60e9`; use Timedelta arithmetic.
- **Floating-point cancellation** in LP post-processing gave net = −1.6e-15 kW. Billing rejects
  negative net, so no-export is enforced exactly (`discharge = min(discharge, load + charge)`).
- **CSV float parsing** can differ from in-memory values in the last bit. Savings are always read
  back from the CSV cache so a miss and a hit match.
- **A changed summation order** (the fan refactor) shifts NPVs by ~1e-11. Regenerate `docs/m4`; the
  reported numbers don't change.
- **Guard assertions in tests catch vacuous tests** (twice):
  - a replacement test whose fixture already had the replacement;
  - an e2e test where every month was idle.
- **Generated sentences must take verdicts from the numbers.** A canned "barely changes" once
  contradicted "15 of 40 sites move".
- **Churn sign:** check that churn lowers value. Stopping O&M at churn made churn helpful when
  savings < O&M.
- **Monte Carlo noise:** at 2,000 draws, P10 noise (~$1.9k) exceeded neighbor gaps. Hence 8,000
  draws and a noise-aware "moved" threshold.
- **Peers in ComStock** look unrealistically good (shared prototype schedules).
- **ComStock "county"** is a weighted allocation, not an address. Utility is a building attribute.
- **Don't trust "it parsed":** print parsed data from new files. That's how the glued-URL bug was
  found.
- **Scripted file edits:** assert each match; scratch Python next to downloads must run with `-I`
  (a scratch `inspect.py` once shadowed the stdlib).

---

## 11. Definition of done for anything new

- **Gate:** `make check` passes on every commit, gated on the exit code. CI is green.
- **Provenance:** new numbers about the world go in `assumptions.yaml` with a source URL or
  `ASSUMPTION`, with a range if uncertain.
- **Tests:** unit tests for pure functions, a property test where invariants exist, a regression
  test for each bug, and the golden file updated deliberately if numbers change.
- **Docs:** regenerate affected docs (`scripts/report_ranking.py`, M2 scripts). Update AI_LOG
  (what was wrong and how it was caught), DECISIONS (ADR), LIMITATIONS and README status.
- **Delivery:** open a PR with a clear summary and test plan, watch CI only, and end with a 5-line
  summary for the user.
