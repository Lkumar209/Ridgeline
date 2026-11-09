# Limitations

Plain statements of what this model does not capture. All outputs are **illustrative**. This
list grows each milestone.

## Load data
- **Modeled buildings, not meters.** ComStock loads come from EnergyPlus prototype models
  calibrated at stock level. Real meters are noisier, with equipment cycling, occupancy surprises
  and outages. That noise tends to make peaks spikier, so modeled loads may *understate* how
  much a battery can shave, or misstate which hours set the peak.
- **One weather year (AMY 2018).** There is no year-to-year variation in the load data itself.
  Year-to-year load risk has to be represented explicitly in the Monte Carlo (M4).
- **Location is a statistical allocation.** ComStock spreads each sampled building across several
  counties and tracts by weight. A site's county is its highest-weight allocation, and its utility
  is a separate building attribute, so the two may not agree with real service territories. There
  are no coordinates. The map (M5) will use approximate area centroids.
- **Sample, not census.** 40 sites drawn by a seeded, stratified rule (DECISIONS.md ADR-004).
  They are not a representative sample of MA buildings, and the rule deliberately over-represents
  flat (low peak-to-average) loads to spread the ranking.

## Gap imputation (M2)
- **Validated on modeled data.** The imputers were scored by hiding stretches of clean ComStock
  data. Real meters add noise, partial outages, and outages that hit neighboring sites together
  (storms), so real-world errors will be larger.
- **The peer method looks better than it would in reality.** Same-type ComStock buildings share
  prototype schedules, so peers track each other unrealistically well. It is not the default for
  this reason (ADR-007).
- **Schools and strip malls are the hardest** (about 11–15% median peak error even for the regression),
  because academic calendars and tenant mixes are not features.
- **Calendar months stand in for billing cycles.**

## Tariffs
- **Supported structure.** Energy charges by time-of-use period, monthly flat demand charges,
  time-of-use demand charges, and a monthly fixed charge. Tiered rates, per-day fixed charges and
  non-kW demand units are rejected, not approximated.
- **Demand ratchets are ignored** when present, and the tariff is flagged `ratchet_ignored`.
- **Holidays** are treated as ordinary weekdays; URDB weekend schedules apply to Saturdays and Sundays only.
- **Supply vs. delivery.** Results depend on which charges the committed tariff files include.
  Each file's source URL is the reference.

## Battery and dispatch (M3)
- **Months are independent** and the battery starts each month full. State of charge is not
  carried across month boundaries.
- **No degradation within a year.** Capacity fade enters in M4 as a per-year derate.
- **The practical controller only defends one threshold** (the all-hours monthly peak). It ignores
  energy prices and TOU-demand windows, so under TOU tariffs it leaves arbitrage and window-specific
  savings to the LP bound.
- **The persistence forecast is crude.** Each month starts at the threshold that would have held
  last month. Median capture versus perfect foresight is 51% on the dev subset under G-2.
- **The first month is idle.** With a single data year there is no history before January, so the
  practical battery does nothing that month. That is causal but slightly pessimistic; a real site
  would have last year's data. The earlier December wraparound was a lookahead and is now only an
  opt-in comparison (`--wraparound-lookahead`).
- **Idle months.** If dispatch would cost more than no battery in a month, that month is billed
  as idle. This assumes the operator can tell, which slightly flatters the controller.
- **No export, and no wholesale or demand-response revenue.**

## Cash flow and ranking (M4)
- **Savings come from the practical controller.** It captures a median ~51% of the perfect-foresight
  bound on the dev subset, so the M4 NPVs are a conservative view of what a better controller could
  earn.
- **Demand savings scale linearly with the demand-charge multiplier and with remaining capacity.**
  Dispatch is not re-simulated per draw. A degraded battery is assumed to save proportionally less,
  which is a simplification for peak shaving.
- **Year-to-year load variation is synthetic noise** (10% lognormal), because there is one weather year.
- **Churn ends savings permanently, with no re-tenanting and no battery resale.** Hazards by building
  type are relative guesses.
- **One generic upfront incentive fraction (0–30%)** stands in for capex-reducing incentives (for
  example a storage tax credit), whose terms and eligibility are not modeled.
- **No recurring program revenue.** Demand-response payments (for example ConnectedSolutions) are
  left out. The model reports the revenue each site would need instead of assuming an amount, so
  "not viable" means "not viable on bill savings alone".
- **Costs mix sources:** ATB 2022$ costs are converted to 2025$ with an assumed ×1.10 factor; the
  tariff is 2025.
- **Rank positions within about 4 places are ties** (Monte Carlo noise between seeds).
- **Imputation error is not propagated.** The current sites have no real gaps; real meter data would
  need the M2 error distribution added.

## API and map (M5)
- **Map pins are approximate.** Each pin is placed at its PUMA centroid plus an offset of about 1 km;
  ComStock has no addresses.
- **Rank colors use 5 groups of 8,** because ranks within about 4 places are ties.
- **The API serves the last `ridgeline rank` run.** It does not recompute, and after a new run it
  needs a restart.
- **The page needs the internet** for the Leaflet library and OpenStreetMap tiles. Tests don't.
- **No auth, no database, local use only.**
- **Downloads retry transient failures** (4 attempts; 2, 4, 8 s waits). A run that keeps
  failing still stops with the URL and the error.

## LLM agent layer (M6)
- **Live results are from very few runs.** On claude-opus-5-5 the first live run passed 9/11 and,
  after the fixes in AI_LOG, a second passed 11/11. Outputs vary run to run: in 3 re-runs of one
  explanation case, 1 dropped the "never pays back" caveat (the validator rejected it). Treat
  11/11 as "works", not as a measured accuracy.
- **Offline evals test the harness, not the model.** `make evals` uses hand-written answers.
- **The validators check grounding, not truth.** An extracted value can be correctly quoted from a
  tariff that is itself outdated or for the wrong rate; a quoted number can sit in the right
  sentence but belong to a different charge. Review flagged fields and the evidence quotes.
- **Number matching is lexical.** A number in an explanation passes if it rounds from any number
  in the facts, not necessarily the right one. Signs are ignored ("loses $217k" and "-$217k" both
  match). Spelled-out numbers are recognized in tariff text but not in explanations.
- **Small eval set.** 11 cases, mostly synthetic snippets; one real tariff text (G-2's URDB
  description). It shows the method, not a measured accuracy.
- **Extraction covers flat demand tariffs only.** Time-of-use windows, seasonal rates and ratchets
  have no fields yet; such text ends up in notes.

## MECo G-2 tariff (`data/tariffs/meco_g2_sema.json`)
- **Delivery service only.** The record's `servicetype` is Delivery. Supply (basic service) energy
  costs are excluded, so round-trip losses and energy arbitrage are under-valued
  (`bill_scope_delivery_only`). Demand-charge savings are unaffected.
- **Unapproved record.** The URDB record is marked `approved: false`. Its sources are National
  Grid's `meco_delivery.pdf`, `meco_basic_service.pdf` and `meco_g2.pdf`.
- **Billing demand simplified to the 15-min kW peak.** The tariff also has a clause of 90% of the
  kVA peak above 75 kW, and a 5 kW floor. At our assumed power factor of 0.90, the kVA clause gives
  the same number (`billing_demand_basis`).
- **Load zone.** The record is labeled for the SEMA load zone. That should not change delivery
  charges, but it would matter if supply were included.
- **Eligibility.** The tariff applies up to 200 kW, with average use above 10,000 kWh/month.
  Sites above 200 kW are on G-3 (below).

## MECo G-3 tariff (`data/tariffs/meco_g3_sema.json`, ADR-016)
- **2025 rates, not today's.** Both tariff files are the URDB snapshot effective 2025-02-01.
  National Grid's current summary (changes through 2026-10-01) lists G-3 demand at $10.61/kW (file:
  $8.55) and G-2 at $15.24/kW (file: $14.82). Values would rise for every site; G-3 sites would
  gain relative to G-2 sites. The ±30% all-sites demand sweep brackets the size of the change, but
  a G-3-only increase has not been run as a scenario.
- **Energy rates look like the distribution component only.** The record says "Retail Delivery
  Price" but its $0.01074/$0.00815 per kWh match National Grid's distribution rate, not the full
  delivery price (~$0.066/kWh in 2026). G-2's file uses the full price. This understates the cost
  of battery round-trip losses on G-3 sites; demand savings are unaffected.
- **Holidays.** The tariff treats 9 holidays as off-peak. URDB schedules cannot express holidays,
  so the model bills demand on those weekdays too (slightly conservative for the battery).
- **Billing demand simplified** to the 15-minute kW peak in peak hours; the 90%-of-kVA clause is
  handled as for G-2 (`billing_demand_basis`). The optional transmission coincident-peak billing
  is not modeled.
- **Controller in time windows.** The practical controller now discharges only in billed hours
  (ADR-016). Across the 23 G-3 sites it beats the all-hours rule on 15 and loses on 4 (median
  savings $2,266 vs $2,084 per year). It still captures only ~45% of the perfect-foresight bound.

## Not modeled (by design, per the brief)
- Wholesale market, capacity or demand-response revenue.
- Interconnection costs and timelines.
- Incentive program details beyond what `assumptions.yaml` states with a source.
