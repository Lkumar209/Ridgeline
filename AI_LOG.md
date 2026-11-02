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
