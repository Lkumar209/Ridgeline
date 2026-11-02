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
