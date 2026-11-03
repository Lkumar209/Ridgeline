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
  - EIA 11804 sites above 200 kW are billed on G-2 values as a labeled proxy (ADR-010). Their
    savings are indicative only; a real large-customer rate (G-3) is time-of-use.
  - M4 sweeps the demand charge by about ±30% to test whether rankings survive a wrong proxy.

## Not modeled (by design, per the brief)
- Wholesale market, capacity or demand-response revenue.
- Interconnection costs and timelines.
- Incentive program details beyond what `assumptions.yaml` states with a source.
