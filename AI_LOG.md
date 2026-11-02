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
