# Decisions

Short ADR-style records. Each one covers the context, the decision, the alternatives we rejected,
and the consequences. Newest at the bottom.

## ADR-001: Use real NREL ComStock loads, not a synthetic generator (M0)

**Context.** We need 15-min load curves for MA commercial buildings. The M0 spike found ComStock
2024 release 2 on the OEDI public S3 bucket reachable without a key, with MA metadata,
timeseries and county weather (`spikes/m0_data_feasibility.md`).

**Decision.** Use ComStock `comstock_amy2018_release_2`, `upgrade=0` (baseline buildings).

**Rejected.** A synthetic load generator. It would be easier to control but would teach the ranking
nothing about real load shapes. It also needs invented parameters, which runs against principle 2.

**Consequences.** Loads are *modeled* buildings for one weather year (2018), not metered sites
(LIMITATIONS.md). The fetch needs network access to `oedi-data-lake.s3.amazonaws.com`. Tests
use small committed fixtures, so they run offline.

## ADR-002: Tooling and dependencies (M1)

`uv` for environments and the lockfile. `ruff` for lint and format. `mypy --strict` on the whole
package. `pytest` and `hypothesis` for tests. Runtime dependencies, each with a reason:

| Dependency | Why |
|---|---|
| numpy, pandas | Interval time series and vectorized math. The standard choice, and reviewers know them. |
| pyarrow | ComStock ships parquet. |
| pydantic | Validated models at module boundaries (`data/schemas.py`) and for config. |
| pyyaml | `config/default.yaml` and `assumptions.yaml` are human-edited YAML. |
| typer | Small typed CLI with no boilerplate. |
| httpx | Streaming downloads with timeouts. |

**Rejected.** polars or duckdb (faster, but nothing here needs it, and they are less familiar to a new
teammate), and requests (httpx covers the same ground). Later milestones add scipy (M3 LP bound),
matplotlib (M2 plots), fastapi (M5) and anthropic (M6), each justified when it is added.

## ADR-003: Timestamp convention, standard time and interval-ending (M1)

**Context.** Demand charges apply in wall-clock windows (for example weekdays 8:00–20:00 local).
A one-hour error would shift every on-peak window for the seven months of daylight saving.

**Evidence (real data):**
1. Raw ComStock stamps are a perfectly regular 35,040-row year from `2018-01-01 00:15` to
   `2019-01-01 00:00`. Local prevailing time would have a 23-hour day in March and a 25-hour day in
   November. So the stamps are in a fixed-offset zone and mark the interval *end*.
2. Weather GHI peaks at the 12:00 hour-ending stamp in both January and July. That is solar noon in
   standard time (about 11:45 EST in Boston), not UTC.
3. In five buildings, the weekday lighting schedule runs exactly 1 h *earlier* in raw stamps during
   EDT than during EST. Building schedules follow daylight saving and the timestamps don't.

**Decision.** Treat source stamps as naive UTC-5, interval-ending. Convert once at load time to
UTC interval-start (`data/timestamps.py`). Apply tariff windows after converting to
`America/New_York`.

**Tests.** `tests/unit/test_timestamps.py` pins the pure conversion: 92 intervals on the March DST
day, 100 on the November one, and a July stamp landing an hour later on the wall clock. It also
checks on real fixture data that the lighting schedule lines up on the same wall-clock time in
February and July after conversion, but is 1 h apart before it.

## ADR-004: Site selection (M1)

**Decision.** 40 sites: 8 building types × 5. Annual 15-min peak between 100 and 1,000 kW. Within each type,
2/1/2 sites come from the low/mid/high tercile of the peak-to-average ratio (PAR), drawn with
seed `20261102`. Low-PAR (flat) sites are included on purpose, as likely weak candidates, so the
ranking has spread. Only buildings simulated in MA are used. Sites are limited to utilities
EIA 11804 and 54913, which serve about 72% of screened candidates, so two utilities' tariffs cover every site.
Counties are Middlesex, Worcester, Suffolk and Hampden (Boston area, central and western MA).
A 10-site dev subset is the first two rounds of a round-robin over types, with each type's PAR
tier rotated so the subset mixes tiers.

**Context worth knowing.** ComStock *allocates* each sampled building to several counties and
tracts by weight (on average about 7 counties per building). A building's "county" here is its
highest-weight allocation among the four study counties, not a street address. Utility is a fixed
attribute of each building and doesn't depend on the allocation, so county and utility territory
are not guaranteed to agree with real geography.

**Rejected.** Pure random sampling, which over-weights high-PAR retail and gives no
guaranteed spread. Choosing sites by hand, which isn't reproducible and invites cherry-picking.

**Consequence.** The utility mix is uneven: 35 sites for 11804 and 5 for 54913. That reflects the
candidate pool (about 72/28) plus sampling noise.

## ADR-005: Tariffs from URDB-format JSON files; refuse what we can't model (M1)

**Context.** The URDB API is blocked in the dev environment (`api.openei.org`). The project owner
will commit 2–3 real tariff files.

**Decision.** `data/tariffs/*.json` holds URDB API v8 records (a single record or the
`{"items": [...]}` envelope), so a live URDB client can be added later without touching the
parser. Sites are matched to tariffs by `eiaid` and the tariff's kW eligibility limits. More than one
match is an error. The parser *rejects* tiered rates, per-day fixed charges and non-kW demand
units instead of approximating them. Demand ratchets are flagged (`ratchet_ignored`) and ignored,
and LIMITATIONS.md says so.

**Rejected.** Hand-entering rate values in YAML, which is easy to mistype, has no provenance,
and doesn't match URDB.

## ADR-006: Branch workflow in a pinned cloud session (M0)

The cloud session can push only `claude/dazzling-cori-pty3ol`. Each milestone is one PR from that
branch into `main`. After a merge, the branch restarts from the new `main`.

## ADR-007: Gap imputation, regression on weather and time; judge by billing peaks (M2)

**Context.** Meter outages of 1–3 months must be filled before billing simulation. What matters
is each month's peak kW (it sets the demand charge), not interval MAE.

**Decision.** The default imputer is ridge least squares on weekday/weekend × 15-min-slot dummies plus
cooling and heating degree terms, fit on the site's own observed data (`gaps/impute_model.py`). The
seasonal-profile fill is kept as the baseline. A peer-site feature is available but not the
default. Methods are scored on monthly peak error and bias, with MAE/MAPE secondary
(`docs/m2_imputation.md`).

**Why not peers by default.** On ComStock, same-type buildings share prototype schedules, so the
peer signal is unrealistically clean. *(Updated in M4: on the original site list, the peer
variant's median peak error was mixed. On the current 40 sites it wins on every breakdown, which
fits the "inflated by shared prototypes" explanation, so the default stays until it can be tested on
real meters.)*

**Rejected.** Gradient boosting or other ML libraries: a new dependency, harder to explain, and
the linear model already removes most of the bias. Hourly dummies: they increase the peak bias
(−5.4% vs −3.4% for the regression on the current sites), though their median absolute error is
slightly lower. That trade-off is measured in the M2 doc. Hinge temperatures and ridge λ live in `config/default.yaml` as
modeling choices, not facts.

**Consequence.** Imputed months still carry roughly −21% / +12% peak error at P10/P90. M4 must sample that
error rather than treat filled data as known.

## ADR-008: Battery dispatch and billing (M3)

**Decision.**
- **Billing:** each local calendar month is billed and simulated independently, with the
  battery starting full.
- **Practical controller:** a threshold rule with a ratchet. Its starting threshold is the lowest
  threshold it could have held over the *previous* month (persistence: history only). The first
  month of the data has no history, so the battery is idle that month. *(Amended: originally
  January borrowed December of the same data year, which is a lookahead. It was removed at the
  project owner's request; median capture on the original dev subset went from 0.565 to 0.544.)*
- **Upper bound:** a perfect-foresight LP per month (scipy HiGHS, sparse) defines the capture ratio.
- **Diagnostic:** an "oracle threshold" run isolates the threshold forecast from the rule itself.
- **Idle guard:** a month whose dispatch costs more than no battery is billed idle and flagged,
  because an operator can always leave it off. So bill(with) ≤ bill(without) holds by construction.

**Why.**
- The threshold rule is what a simple commercial controller does, and it is explainable in one sentence.
- Independent months keep billing modular and make the LP small: about 3,000 intervals and about 9,000 variables.
- With a perfect threshold the rule matches the LP's peak reduction (`docs/m3_dispatch.md`), so the
  rule is sound and the open problem is forecasting. That is where future work should go.

**Rejected.**
- **cvxpy:** heavier dependency; the LP is small and scipy's HiGHS solves it directly.
- **MILP to forbid simultaneous charge and discharge:** cost-neutral cases don't change the bill, and
  MILP is much slower.
- **Carrying SoC across months:** a marginal effect, and it couples months, making billing and tests harder.

## ADR-009: Tariff eligibility, kVA demand and coverage (M3)

**Decision.**
- **Eligibility:** a site matches a tariff when the utility EIA ID matches, its annual 15-min peak
  is inside the kW limits, and its *average* monthly kWh is inside the usage limits. Exactly one
  match is required; zero or several raise `TariffMatchError`, and `simulate` exits listing every
  failing site.
- **$/kVA demand charges** are converted to $/kW as rate / PF with
  `power_factor_for_kva_demand` (ASSUMPTION, 0.90), and the tariff records the PF used.
- **MECo G-2's kVA clause above 75 kW** is simplified to the 15-min kW peak (`billing_demand_basis`, ASSUMPTION).

**Open.** Average-month vs every-month usage eligibility (the stricter reading drops one site). Coverage is
13 of 40 sites under G-2 alone. Options and a recommendation are in `docs/m3_dispatch.md`; the
site list is unchanged pending the project owner's decision.

**Rejected.** Picking the "closest" tariff when none matches, which hides a data gap. Silently ignoring kVA
units, which gives a wrong $/kW by a factor of 1/PF.

**Dependency.** scipy (runtime) for the LP; scipy-stubs (dev) for typing. A one-line type ignore
covers the stubs not declaring sparse-matrix support in `linprog`.

## ADR-010: Tariff coverage, a labeled G-2 proxy and the NSTAR replacement (M3)

*Point 2 (the proxy) is superseded by ADR-016; the proxy mechanism remains in code, unused.*

**Context.** The only usable real tariff is MECo G-2 (EIA 11804, ≤ 200 kW, average use
> 10,000 kWh/month). It covered 13 of the original 40 sites. No usable NSTAR (EIA 54913) rate was
found, and the MECo G-3 records found are 115 kV service.

**Decision** (project owner, from the options in `docs/m3_dispatch.md`):
1. **Usage eligibility uses the average month.** The tariff text says "average use will exceed
   10,000 kWh/month".
2. **Proxy for large 11804 sites.** Sites above 200 kW are billed on G-2's rates via
   `tariff_proxies` in config. The proxy is labeled `g2_proxy_above_200kw` (ASSUMPTION), carries
   the id `…+proxy>200kW` and is flagged `tariff_is_proxy` in every output. A test requires each
   proxy to name an ASSUMPTION.
3. **NSTAR sites replaced.** The 5 NSTAR sites are swapped for 11804 sites of the same building
   type and PAR tier (`replace_utility_eiaids: [54913]`). This uses a separate seeded draw, so the
   other 35 sites are unchanged; a test enforces that.
   - cs-38821 → cs-9978 (RetailStripmall, mid)
   - cs-42670 → cs-65325 (FullServiceRestaurant, mid)
   - cs-65258 → cs-45394 (PrimarySchool, mid)
   - cs-104743 → cs-106921 (SecondarySchool, high)
   - cs-104750 → cs-39283 (SecondarySchool, low)
4. **Keep looking for a real large-customer rate (G-3).** In M4, the demand charge is swept by
   about ±30% so the ranking shows whether it survives a wrong proxy.

**Coverage now.**

| | Real G-2 | G-2 proxy (> 200 kW) |
|---|---|---|
| All 40 sites | 17 | 23 |
| Dev subset (10) | 6 | 4 |

**Rejected.**
- **Re-selecting all 40 from 11804 only:** it would have reshuffled the 35 kept sites and the dev
  subset for no reason.
- **Proxying NSTAR with a MECo tariff:** a different utility, which stretches too far.
- **Inventing a G-3 rate:** violates principle 2.

**Consequence.** The M2 imputation results (`docs/m2_imputation.md`) were computed on the
original site list. Rerunning `scripts/evaluate_imputation.py` refreshes them.

## ADR-011: Monte Carlo cash flow and robustness ranking (M4)

**Decision.**
- **Score:** rank by **P10 NPV** (robustness), and show P50 rank, P(NPV>0) and breakeven capex
  alongside.
- **NPV model:** one vectorized function (sites × draws × years) serves both the Monte Carlo and the
  deterministic tornado, so there is one cash-flow formula to review.
- **Shared draws:** global uncertain inputs are drawn once and shared by all sites. Per-site noise and
  churn are seeded by `(seed, bldg_id)`. Churn departure years come from fixed uniforms by inverse
  CDF, so every scenario comparison reuses the same randomness.
- **Churn semantics:** when the tenant leaves, savings stop and the fixed O&M continues.
- **Proxy sweep:** the demand-charge sweep (×0.7–1.3) applies to proxy-tariff sites only, with an
  all-sites contrast.
- **Noise-aware "moved":** a site counts as having moved only if it shifts more places than a
  second random seed moves any site (5+ places with 8,000 draws).
- **Sources and caching:** capex and O&M from NREL ATB 2024 (sourced); other inputs ASSUMPTION
  with ranges. Simulated savings are cached under a fingerprint.

**Why.**
- **P10 rewards sites that hold up in bad futures.** That is what "robust" means here, and it is easy
  to say in one sentence.
- **Shared draws make site comparisons and scenario comparisons attributable.**
- **Churn semantics:** my first version ended O&M at churn too. With savings below O&M, that made
  churn *raise* NPV, which is backwards. The battery stays with the building, so its maintenance
  contract continues.
- **Noise-aware "moved":** with 40 sites a few hundred dollars apart, a fixed "3 places" threshold
  counted Monte Carlo noise as a result.

**Rejected.**
- **Ranking by mean NPV:** it hides tail risk, which is the brief's point.
- **A composite robustness score:** harder to explain, and P10 alone captures the question.
- **Triangular or fitted distributions:** uniform ranges are the honest choice when the bounds are
  all we know.
- **Re-simulating dispatch per draw:** about 8 s per site-year; demand savings are scaled
  analytically instead (exact for the threshold controller, except for months the idle guard
  switches off).

**Consequence.** No site pays back at central costs; the ranking orders sites by how little they
lose,
and how reliably. Cost inputs decide *whether* storage pays; churn and the proxy tariff decide *where*.

## ADR-012: Report the other revenue needed, don't assume program amounts (M4 follow-up)

**Context.** No site is viable on demand-charge savings alone. Real projects often stack recurring
revenue such as utility demand-response payments, but we have no sourced, current amounts for them.

**Decision.**
- **Upfront incentive scope:** `upfront_incentive_fraction` covers upfront, capex-reducing incentives
  only.
- **Recurring revenue is reported, not assumed:** each site gets the annual $/kW-year it would need to
  break even (central case), plus a viability table over a $0–200/kW-year sweep.
- **Breakeven capex ($/kW) is the main companion metric to the rank.** It tells a reader how far from
  viable each site is when NPVs are uniformly negative.

**Rejected.** A "stacked incentives" scenario with a guessed $/kW-year: it would present an unsourced
number as a result. The sweep shows the same information without picking a value.

## ADR-013: A read-only API over rank outputs, and one static page (M5)

**Decision.**
- **API:** FastAPI serves the files `ridgeline rank` writes (`ranking.csv`, `fan.csv`,
  `explanations.json`, `revenue_sweep.csv`), plus daily load from the cache. It never runs the
  simulation or the Monte Carlo.
- **Testability:** `create_app()` takes a data provider, so tests inject in-memory data and run
  offline.
- **Missing results** return 503 with "run `ridgeline rank`".
- **Page:** one static page with vanilla JS and hand-written SVG charts. Leaflet comes from a pinned
  CDN URL with integrity hashes.
- **Map colors:** pins are colored in 5 rank groups on a validated ordinal ramp.
- **Locations:** PUMA centroid plus a deterministic offset, labeled approximate.
- **Cash-flow fan:** `npv()` became the sum of `discounted_cashflows()`, so the fan chart and the
  ranking share one formula; a test checks the fan's last year equals the NPV percentiles.

**Rejected.**
- **A database:** 40 sites fit in memory, and files keep the pipeline inspectable.
- **A JS framework or chart library:** two small charts don't justify a build step.
- **Computing in the API:** results could disagree with `docs/m4`.
- **40 distinct colors:** this would imply rank precision the model doesn't have.
- **Geocoding real addresses:** there are none.

## ADR-014: An LLM layer that drafts, and deterministic validators that decide (M6)

**Decision.**
- **One seam:** `agent/client.py` defines an `LLMClient` protocol with one method. Extraction and
  explanation code never import the SDK. Live runs use `AnthropicClient`; tests and `make evals`
  use a deterministic `MockClient`.
- **Model and key:** the model comes from `$RIDGELINE_LLM_MODEL`, else `config/default.yaml`
  (`agent.model`). The key comes only from `$ANTHROPIC_API_KEY`, read by the SDK; Ridgeline only
  checks that it is set and never reads, logs or prints it. Live commands exit with code 2 and a
  message when it is missing.
- **Structured output for extraction:** the request carries the pydantic model's JSON schema
  (closed objects, every field required, nullable values), so the response always parses.
- **Every field carries evidence.** Each extracted field is `{value, confidence, evidence}`, where
  evidence must be an exact quote. The validator rejects:
  - a value whose quote is not in the source (after whitespace normalization);
  - a quote that does not contain the value (rounding, percent-to-fraction and cents-to-dollars
    allowed; spelled-out numbers like "fifteen" allowed);
  - evidence without a value, a value without evidence, and confidence outside 0..1.
  Low confidence is a warning for a person to review, not a rejection.
- **Explanations are grounded in a fixed facts list** (`render_facts`), built from one row of
  `ranking.csv`. The validator rejects any number that does not round from a number in the facts,
  any site ID not in the facts, "best/top/worst" without a measure in the same sentence, a missing
  site ID, and a missing caveat ("never pays back" for sites whose breakeven is ≤ $0/kW; "proxy" for
  proxy-tariff sites). Computing new numbers (differences, ratios) is therefore rejected by design.
- **Evals:** `agent/evals/cases.yaml` has 11 cases (6 extraction, 5 explanation). A case passes
  only when the validator accepts the output and the output is correct. Offline, the mock returns
  hand-written answers (labeled as such), so the evals test the harness, prompts and validators;
  `ridgeline evals --live` scores a real model on the same expectations.
- **Refusals:** for models that support it, requests opt into the server-side refusal fallback;
  a refusal or truncated output raises `AgentError` instead of returning partial text.
- **Dependency:** `anthropic` (the official SDK), imported lazily so offline code paths don't need
  it at runtime.

**Rejected.**
- **Trusting confidence scores alone:** self-reported confidence is not evidence; the quote check
  is what stops a guess.
- **Letting the model compute or compare numbers in explanations:** unverifiable by a simple check,
  and the existing sentences in `ranking/pipeline.py` already do that deterministically.
- **An LLM judge for the evals:** the expectations here are exact values and phrases, which code
  can check.
- **An API endpoint or map-page integration:** it would put live-model latency and a key into the
  read-only API (ADR-013). The CLI is enough for M6.
- **Recording real model responses as the mock fixtures:** no key was available in the build
  session; hand-written answers are labeled as hand-written instead of being passed off as recorded.

**Amendment (live run).** "There is no demand charge" is a stated value of 0, not a missing one.
The validator accepts 0 only when the quote says "no/without … charge", so an unrelated negation
("must not exceed 200 kW") cannot justify a zero.

## ADR-015: Retry only transient download failures

**Decision.** `data/cache.py::download` retries connection errors, timeouts, 429 and 5xx up to
4 attempts with waits of 2, 4 and 8 seconds, and removes the partial file between attempts. Any
other 4xx (including a proxy's 403 for a blocked domain) fails at once.

**Rejected.** Retrying every error: a blocked domain must be reported immediately (a rule from the
brief), not after a minute of retries. A retry library: one loop is clearer than a dependency.

## ADR-016: Real MECo G-3 for sites above 200 kW, and a window-aware controller

**Context.** ADR-010 billed the 23 sites above 200 kW on G-2 values as a labeled proxy, because the
only G-3 records found then were 115 kV service. With an OpenEI key, URDB lists a secondary-voltage
"G-3 Time of Use SEMA Load Zone" record from the same 2025-02-01 snapshot as our G-2.

**Decision.**
- **Tariff:** commit URDB `67d0b140ad6db765a70b0a5c` verbatim as `data/tariffs/meco_g3_sema.json`.
  It is the Delivery record; its twin `67d0b147…` adds supply ("Delivery with Standard Offer").
  This matches the delivery-only G-2 record. Eligibility (≥ 200 kW), the weekday 8 a.m.–9 p.m. peak
  window, 15-minute demand and the holidays were checked against National Grid's `meco_g3.pdf`
  (M.D.P.U. No. 1591). A data-contract test pins the values and the billed window.
- **Same snapshot for both tariffs,** even though National Grid's 2026 rates are higher (G-3
  $10.61 vs $8.55/kW; G-2 $15.24 vs $14.82/kW). Every tariff number keeps a single source file,
  and the two tariffs stay comparable. The drift is documented (`tariff_rate_vintage`).
- **No proxy:** `tariff_proxies` is empty. The proxy-only sweep and its sentence run only when a
  proxy site exists; the tornado drops the proxy input in that case.
- **Window-aware controller:** `threshold_dispatch` and `feasible_threshold` take a `billed` mask
  (from `demand_billed`: intervals with a flat demand rate or a TOU demand rate above 0). Outside
  billed hours the battery does not discharge and recharges at full power. With every interval
  billed (G-2) the code path is unchanged, and a test checks the mask-of-all-True is identical.
- **Ranking carries `tariff_id`,** so explanations can name each site's real tariff.

**Rejected.**
- **Hand-transcribing 2026 rates from the PDF:** the brief allows it only with the owner's OK, and
  mixing a transcribed G-3 with a URDB G-2 would compare tariffs from different years.
- **The "Delivery with Standard Offer" record:** it would add supply energy for G-3 only.
- **Keeping the all-hours controller for G-3:** measured worse on 15 of 23 sites.

**Consequences.** No site pays back in any future (the G-2 proxy had one 1-in-8,000 positive
draw). G-2 sites take 8 of the top 10. The most robust site is now cs-70654 (G-2).
