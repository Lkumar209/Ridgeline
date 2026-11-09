# AI log

What the AI assistant (Claude Code) produced at each milestone, what was wrong or rejected, and how
it was caught. Newest milestone at the bottom.

## M0: data feasibility spike

**Key prompts**
- The project brief, followed by "enter plan mode; restate the goal, flag risks, propose layout, detail M0/M1."
- Plan decisions from the user: one PR per milestone from the session branch into `main`. If URDB
  is blocked, pause and report rather than hand-transcribe a tariff.

**What was generated**
- Plan (repo layout, M0/M1 approach and acceptance criteria).
- Read-only network probes, S3 listings, and `spikes/m0_probe.py`, which reproduces every number in
  `spikes/m0_data_feasibility.md`.

**What was wrong or rejected, and how it was caught**
1. *Assumed one metadata row per building.* The Middlesex file has 35,285 rows but only 2,936 unique
   `bldg_id`s, because rows are building × tract allocations. I caught this by checking `nunique()` against
   `len()`. Fix: site selection must de-duplicate on `bldg_id`. A test for this goes in M1.
2. *Assumed every building in a state's metadata was simulated in that state.* 949 of 2,936 were
   "as simulated" in Connecticut. I caught it by inspecting the `in.as_simulated_*` columns while looking for
   location fields. Fix: filter `in.as_simulated_state_name == "Massachusetts"`.
3. *Planned to use the smaller "basic" metadata file.* It lacks the peak-demand and utility-ID
   columns needed for site screening. I caught this by grepping its columns. The decision is to use the "full" file and slim it.
4. *Plan said map points would be "jittered county centroids".* The data has census-tract codes, so
   tract centroids are possible. The plan detail will be revised in M5.
5. *Did not assert which utility each EIA ID belongs to.* I'm leaving it as an open item to verify, not
   a guess (principle 2).

## M1: scaffold, schemas, 40 cached sites

**Key prompts**
- The user's M0 decisions: real ComStock data; 40 sites over 8 types, 100–1,000 kW, 3–4 counties,
  MA-simulated only, include low peak-to-average sites, and a 10-site dev subset; tariffs come from
  JSON files the user will add; resolve the timestamp convention with a test.

**What was generated**
- uv project, `make check`, pydantic schemas, config, the assumptions validator, the ComStock
  loader and site selector, the URDB-format tariff parser, the weather loader, the `fetch-data` CLI,
  real-data fixtures, and 57 tests (unit and property).

**What was wrong or rejected, and how it was caught**
1. *Interval inference used `asi8 // 60e9` (assumes nanosecond resolution).* pandas 3 indexes
   can be in microseconds, so this returned an interval of 0 minutes. Caught by the hypothesis
   round-trip property test and a unit round-trip test. Fixed by using Timedelta arithmetic.
   The same pattern in `check_full_year` was fixed proactively.
2. *First DST test design (50%-threshold "ramp hour") was fragile.* On real fixture data it failed:
   the office has always-on lighting, and the school's July profile is a summer-break schedule.
   Caught by the test failing on real data rather than passing on synthetic data. Replaced it with
   a cross-correlation lag between February and July weekday profiles, and dropped the school from
   that test, with a comment saying why.
3. *County code formatting bug in an exploration script* (`G250010` instead of `G2500010`), which
   returned 404. Caught immediately by `raise_for_status`. Exploration only, not shipped code.
4. *A scratch file named `inspect.py` shadowed the stdlib* when a script ran from that directory.
   Caught by a circular-import traceback. Fixed by renaming it and running scratch Python with `-I`.
5. *Assumed a building's county is its location.* Combining all 14 county files showed each
   building allocated to about 7 counties on average. The decision now records "highest-weight
   allocation", and LIMITATIONS.md states it.
6. *Assumed metadata `peak_demand..kw` might be hourly.* Checked all 40 sites: it equals the max of the
   15-min timeseries exactly, so screening on it is valid.
7. *A test asserting "no DST gap" on a February-only fixture* proved nothing. I removed it; the
   full-year evidence lives in the pure conversion tests and ADR-003.

## M2: gap injection and imputation

**Key prompts**
- "Proceed to M2": inject 1–3 month outages, a simple baseline and one better method (weather,
  building type, time features, similar sites), MAE/MAPE on held-out data, and how much error flows
  into demand-charge estimates. Plot and document it.

**What was generated**
- `gaps/` (inject, features, baseline, regression, evaluate, experiment), the experiment and plot
  scripts, `docs/m2_imputation.md` with figures, and 33 new tests (unit, property, regression).

**What was wrong or rejected, and how it was caught**
1. *Peers were drawn only from the scored subset.* With `--dev-subset`, most sites would silently
   have had no peers, and the code comment claimed the opposite. Caught by reading my own runner
   against its comment, not by a test. Fixed by passing all sites and scoring `score_ids`. Added a
   regression test, and checked it fails when the old behavior is re-introduced.
2. *Hourly time dummies on 15-min data.* Caught by looking at the example plot: step-shaped fills
   that flatten intra-hour peaks. Switched to 15-min slots on principle. The before and after
   numbers are both reported in the M2 doc; one metric (peer median abs peak error) got slightly
   worse, and that is stated rather than hidden.
3. *Draft plot had colliding end labels and a legend covering the data.* Caught by rendering and
   viewing the PNG (the palette validator only checks color). Fixed with label de-collision and an
   outside legend. The palette was validated for color vision deficiency; aqua is below 3:1
   contrast, so the series are direct-labeled and the numbers are also given as tables.
4. *Considered reporting MAE as the headline.* Rejected: MAPE moves only 16.5% to 14.4% across methods
   while billing-peak error halves. Peak error and bias are the headline because they set the bill.
5. *Precomputing the design matrix was expected to fix a 65 s runtime.* Profiling showed the time is
   spread evenly (one-hot build, fits, peak bookkeeping), so the runtime is accepted and stated as the
   M2 budget instead of adding complexity.

## M3: battery dispatch and billing

**Key prompts**
- Threshold controller, a tariff bill calculator, a perfect-foresight bound, and property tests (SoC,
  conservation, peak never raised, bill with battery ≤ without), developed on the dev subset.
- Tariffs: invent none. Report coverage under MECo G-2 (≤ 200 kW); handle $/kVA via an assumed PF;
  fail loudly on 0 or 2+ matches; propose options for unmatched sites and wait for a decision.
- Mid-milestone: the user sent a message saying "here is the URDB JSON", but **no JSON was
  attached**. It was not fabricated from the summary. The eligibility logic (kW and kWh limits) was
  built and tested, and the file remains to be committed.

**What was generated**
- `battery/` (model, dispatch, billing, optimal LP, simulate), `ridgeline simulate`, kVA
  conversion, strict tariff matching, usage-limit eligibility, `docs/m3_dispatch.md`, and 29 new tests.

**What was wrong or rejected, and how it was caught**
1. *LP post-processing produced net load = −1.6e-15 kW.* I had "cleaned" the LP output by cancelling
   simultaneous charge and discharge; floating-point cancellation (17 − 16.99) left a tiny negative
   net, which billing rejected as export. Caught by the hypothesis property test (it shrank the case
   to a 4-interval load). **My first diagnosis was wrong**: I blamed solver tolerance and wrote that
   in a comment. The regression test passed even without the fix, which exposed the mistake. I then
   showed the test fails on the original post-processing and passes on the fix (clip discharge to
   load + charge, and drop the cancellation step), and corrected the comment.
2. *That cancellation step could also push stored energy above `soc_max`.* Found while reasoning
   about the bug above. Removed: simultaneous charge and discharge in the LP is cost-neutral, so it
   is left as solved, and the "no simultaneous" property is asserted only for the threshold rule.
3. *Wrong expectation in a unit test:* I expected a 50 kW recharge after a 30 kW shave. The
   controller correctly recharges only 30 / 0.88 = 34.1 kW (the battery is full again). The test
   was fixed, not the code.
4. *Lazy lambdas in the simulate loop* (ruff B023). They were safe but needlessly subtle, so I replaced
   them with direct calls.
5. *Considered reporting capture ratios from the full fake fixture.* That would conflate demand
   savings with energy arbitrage the threshold rule never attempts. Added a flat-demand-only run,
   which showed the rule matches the LP's peak cut when given the right threshold. The capture gap is a
   forecasting problem.

### M3 follow-up: real tariff, proxy, NSTAR replacement, lookahead fix

**Key prompts**
- The user attached the G-2 URDB JSON and decided: average-month usage eligibility; G-2 as a
  labeled proxy above 200 kW; replace the 5 NSTAR sites from the same strata; fix or label the
  January lookahead and report the effect; real dollar savings on the dev subset.

**What was wrong or rejected, and how it was caught**
1. *Multi-URL `source` silently glued into one invalid URL.* The URDB `source` field held three PDF
   links separated by blank lines. Pydantic's HttpUrl stripped the whitespace and produced
   `…meco_delivery.pdfhttps://…` with no error. Caught by printing the parsed tariff during
   validation instead of trusting "it parsed". Fixed with a list of URLs and a regression test.
   This is the main reason for the data-contract test on the committed file.
2. *I had constructed the URDB link as `/USURDB/…`; the real record says `/IURDB/…`.* It was marked
   "unverified" in `assumptions.yaml`. Caught by comparing against the record's own `uri` once the
   file arrived. Corrected.
3. *A commit was made with a failing test.* A `make check | grep … && git commit` chain does not stop
   on failure, because the pipe hides make's exit code. Caught one step later by reading the test
   output. The unpushed commit was amended after the fix. Since then, commits are gated on make's
   real exit code.
4. *The failing test was vacuous.* The site-replacement test inherited the default config, which by
   then already replaced NSTAR, so "before" and "after" were the same. The guard assertion I had added
   ("the selection contains NSTAR sites") is what failed. Fixed by building the before case
   explicitly.
5. *The January lookahead flattered the controller by about 2 points* (0.565 → 0.544 median capture,
   same sites and tariff). Measured by re-downloading the two replaced dev sites into scratch so the
   comparison is like-for-like.
6. *Rejected: re-selecting all 40 sites from 11804 only.* It would have silently reshuffled the 35
   kept sites and the dev subset. The replacement uses its own seeded draw, and a test asserts the
   other sites are byte-identical.

## M4 prelude: CI and the M2 refresh

**What was generated**
- `.github/workflows/check.yml`, which runs `make check` with uv. Verified offline: data/cache moved
  aside, network proxy pointed at a dead port, `UV_OFFLINE=1`; 130 passed.
- A rerun of the M2 experiment and figures on the current 40 sites, with every number in
  `docs/m2_imputation.md`, ADR-007 and LIMITATIONS updated.

**What changed, and what was wrong**
1. *Two M2 claims didn't survive the new site list.*
   - "Peers are mixed" no longer holds: peers now win everywhere. ADR-007 now says so, and explains
     why the default doesn't change.
   - "Regression improves MAPE" no longer holds: MAPE is 16.1% vs the baseline's 16.0%. The
     headline was reworded, because the billing-peak error is still about half.
   Caught by regenerating every table instead of only the summary.
2. *The hourly-vs-15-min comparison is a trade-off, not a win.* On the new list, 15-min slots
   reduce bias but slightly widen the median absolute error. The doc now presents both sides. The
   M2 entry above records the earlier numbers as history (original site list).

## M4: 15-year Monte Carlo and robustness ranking

**Key prompts**
- Monte Carlo with fixed seeds; P10/P50/P90 NPV, P(NPV>0), robustness score, tornado sensitivity;
  churn as per-site survival risk; demand charge swept ±30% to test the proxy tariff; one
  plain-language sentence each for churn and tariff sensitivity; a stated runtime budget.

**What was generated**
- `scenarios/`, `ranking/`, `results.py`, `ridgeline rank`, `scripts/report_ranking.py` (generated
  `docs/m4/`), `docs/m4_ranking.md`, ADR-011, and 27 new tests (unit, property, golden, end-to-end).
- Capex and O&M sourced from NREL ATB 2024 on OEDI (checked the parquet rows), not invented.

**What was wrong or rejected, and how it was caught**
1. *Churn raised NPV.* My first model stopped O&M when a tenant left. Most sites save less than their
   O&M, so leaving early *helped*. Caught by the generated sentence printing "lowers … by $-2,718"
   (a negative drop). Fixed the semantics (savings stop, O&M continues), and added a property test
   that churn never raises NPV when savings are non-negative.
2. *A canned sentence contradicted its numbers* ("barely its place … 15 of 40 sites move"). Fixed
   by choosing every verdict word from the counts, and by fixing the connector logic.
3. *Rank shifts were partly Monte Carlo noise.* Comparing 2,000 vs 8,000 draws showed P10 moving a
   median $1,071, about twice the gap between neighboring sites. Caught by a convergence check I ran
   before writing the doc. Fixes: default 8,000 draws; a second-seed stability run on every
   `rank`; "moved" counted only above that noise (5+ places).
4. *Vacuous end-to-end test.* Each one-month fixture block was idle under the causal first-month
   rule, so all savings were 0. Caught by a guard assertion that some demand savings are positive.
   Fixed by simulating the two fortnights as one series.
5. *Wrong test expectation:* I asserted energy savings are negative (losses). Under a TOU fixture,
   arbitrage makes them positive. The sign is now asserted only under a single energy price.
6. *An overstated claim in the doc draft:* "perfect foresight is 2–3× higher". The data says a median
   1.95× (range 1.6–3.6×). Caught by cross-checking every quoted number against the CSVs before
   committing.
7. *A silent no-op edit:* a `str.replace` without an assertion left a table header saying "3+" after
   the threshold became 5. Caught by ruff flagging the now-unused variable. Edits to existing code
   now assert their match.

## M4 follow-up, M5 (API and map) and M7 (docs)

**Key prompts**
- M4 follow-up: say exactly what the incentive covers; don't guess program amounts; precise
  headline wording; breakeven as the main companion metric.
- M5: a minimal FastAPI app (sites, rankings, per-site detail) and one Leaflet page (colored by rank;
  click for load curve and fan chart), with API tests. Then M7: README, ONBOARDING with 3 given starter
  features, architecture diagram, fresh-clone test.

**What was generated**
- "Other revenue needed" metric and revenue sweep (ADR-012); PUMA-centroid locations; cash-flow
  fan; `api/` and `web/`; `ridgeline serve`; `make demo`; ONBOARDING.md; docs/architecture.md; a
  README rewrite; 18 new tests.

**What was wrong or rejected, and how it was caught**
1. *A "stacked incentives" scenario would have needed a guessed $/kW-year.* Rejected in favor of
   reporting the revenue each site needs plus a sweep, so no unsourced number appears as a result.
2. *`rank --dev-subset` could not run after `fetch-data --dev-subset`,* because it always simulated
   all 40 sites, and the cache key ignored which sites were ranked. Caught while planning the
   README's dev loop. Fixed, with a regression test.
3. *Cache miss and cache hit gave different NPVs (by ~1e-11).* Caught by a byte comparison of a fresh
   rank against the committed `docs/m4/ranking.csv`. Two causes:
   - pandas' CSV float parser (fixed: always read savings back from the CSV; regression test);
   - the cash-flow refactor changed the summation order (legitimate; `docs/m4` regenerated, with
     every reported number unchanged).
4. *The savings fingerprint ignored `data/tariffs.py` and `data/schemas.py`,* which also change
   bills. Caught while writing ONBOARDING's "likely to break" section. Fixed.
5. *Chart edge labels were clipped ("year 1" for "year 15"),* and the y ticks were odd values.
   Caught by viewing Playwright screenshots, not by tests. Fixed with edge-anchored labels and round
   ticks.
6. *A `pkill -f "ridgeline serve"` killed its own shell* (the pattern matched the command line).
   Switched to stopping the server by its port.
7. *README draft said the first `make demo` takes ~40 s.* The fresh-clone test measured 96 s for
   fetch plus rank. Corrected to "1–2 minutes".
8. *The scratch tooling couldn't reach unpkg or OSM.* Rather than vendor Leaflet, the screenshot run
   routed the pinned CDN URL to a copy from the npm registry. The SRI hashes were computed from that
   same file.
9. *Fresh-clone test* (`git clone` of the pushed branch into an empty folder, then `uv sync`,
   `make check`, `make fetch`, `make rank`, `serve`):
   - 175 tests passed;
   - the regenerated `sites.csv` and `site_locations.csv` were identical to the committed ones;
   - the ranking was byte-identical to the committed `docs/m4/ranking.csv`;
   - the API and page answered.

## Clarity fixes after the user's demo (breakeven wording, "best site", layout)

**Key prompt.** On the user's Mac the demo worked, with three requests:
- show "never pays back, even at $0 battery cost" instead of a negative $/kW;
- say which site "the best site" is when it differs from the top-ranked one;
- tighten the empty space under the map.

The user also asked to confirm "the download-retry PR from my earlier message" was included.

**What was found**
1. *There is no download-retry PR, and no earlier message about one in this session.* Checked the
   PR list (#1–#4 only), the remote branches, and `data/cache.py` (no retry logic). I reported that
   rather than claiming it was included or inventing one.
2. *Two sentences used "the best site" for a site that is not the top-ranked one:* the headline
   and the other-revenue sentence. Both meant cs-118913 (best by median NPV, 6th by P10), while
   the page highlights cs-144167 (1st by P10). I caught the second while searching the docs for the
   phrase after fixing the first. Both now name the site and its rank. Tests assert that the
   ambiguous phrase is gone.
3. *The breakeven wording lives in one Python function* (`breakeven_label`). The API serves the
   label, so the page and the generated docs can't drift from it. An API test checks every row's
   label against its number.

## M6: LLM agent layer, and download retries

**Key prompt.** "Just continue with the work ... I want the whole thing done." The remaining items
in HANDOFF.md were M6 (spec: Anthropic SDK, model from config/env, tariff extraction with per-field
confidence that refuses to guess, grounded site explanations, 10+ evals, a deterministic mock, a
validator that rejects outputs inconsistent with the source) and the download retry.

**What was generated**
- `agent/` (client, numbers, tariff_extract, explain, validators, evals with 11 cases), three CLI
  commands (`evals`, `extract-tariff`, `explain`), `make evals`, an `agent` config section,
  ADR-014.
- Download retries with backoff in `data/cache.py`, ADR-015.
- 51 new tests (232 total).

**What was wrong or rejected, and how it was caught**
1. *The real G-2 text spells the interval out ("fifteen minute peak").* A digits-only number check
   would have rejected a correct answer of 15. Caught while writing the eval case from the real
   URDB description. The validator now also reads spelled-out numbers in evidence.
2. *Cents read as dollars would have passed.* The first evidence check accepted a value matching
   any number in the quote, so 7.33 (instead of 0.0733 $/kWh) from "7.33 cents per kWh" was
   accepted. Caught while listing rejection cases for the tests. If the quote says cents, the value
   must now be the cents figure / 100.
3. *An explanation of P10 as "1 in 10 futures do worse" would have been rejected,* because 10 was
   not in the facts. The system prompt asks for exactly that explanation. Caught by writing the
   mock answers against the validator. The facts now include a one-line reading guide for
   P10/P50/P90.
4. *0.0125% printed as "0.01%".* The share of futures with NPV above zero lost its meaning at two
   decimals for cs-118913. The facts now say "1 of 8,000".
5. *The mock evals pass by construction.* Two non-vacuity tests swap one good canned answer for a
   guess (a demand charge picked from conflicting text; an invented payback period) and assert the
   case fails. A guard test asserts the G-2 description really lacks "14.82", so the
   guessed-demand-charge test can't pass vacuously.
6. *Eval facts could drift from real results.* A test rebuilds every explanation case's facts
   from the committed `docs/m4/ranking.csv` and requires equality.
7. *No live run.* `ANTHROPIC_API_KEY` was not set in the build session. The SDK request shape
   (structured output, effort, refusal fallback) is tested against a fake client, and the README
   and LIMITATIONS say the live path hasn't been exercised.
8. *Lint caught a Unicode minus sign* typed into the number regex; it is now an explicit `−`.
9. *Download retries:* the earlier "download-retry PR" never existed (see the previous entry).
   Built now with a stated policy (transient errors only, so a blocked domain is still reported
   at once), tested with an `httpx.MockTransport`.

## M6 live run

**Key prompt.** The user created an Anthropic API key and asked for the live evals. (The key was
pasted into chat; the user was told it can't be forgotten from the transcript and should be
revoked after the run. It was used only in the command environment, never written to a file.)

**Results on claude-opus-5-5, effort medium**
- First live run: **9/11**. Second, after the fixes below: **11/11**.

**What was wrong, and how it was caught**
1. *The eval was wrong about "no demand charge".* For "There is no demand charge under this rate"
   the model answered 0 with that exact quote. The eval expected null and the validator rejected
   it (no digit in the quote). Zero is the better reading: the text states it. Fixed the expected
   value, the prompt (says so explicitly) and the validator: 0 is accepted only when the quote says
   "no/without … charge". A test checks an unrelated "not" can't justify a zero.
2. *A real omission, caught by the validator.* One explanation of cs-144167 left out "never pays
   back". To see the text, the eval report now prints failed explanations. In 3 more runs of that
   case the caveat was present each time, so this was run-to-run variation, and the validator
   stopped the bad output from being shown. That is the intended design.
3. *The eval was too literal about wording.* It required the word "robust"; the model wrote "ranks
   1 of 40 by bad-case (P10) NPV", which says the same thing more precisely. The expected phrase is
   now "P10" (naming the measure is what matters).

**Lesson.** Two of three live failures were eval mistakes, not model mistakes. Hand-written mock
answers can't show that; a live run is needed before trusting an eval set.
