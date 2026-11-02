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
- **Schools and strip malls are the hardest** (about 10–13% median peak error even for the regression),
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
- **The persistence forecast is crude.** January's starting threshold comes from December of the
  same (single) data year. Capture versus perfect foresight is a median 57% on the dev subset
  (flat-demand structure).
- **Idle months.** If dispatch would cost more than no battery in a month, that month is billed
  as idle. This assumes the operator can tell, which slightly flatters the controller.
- **No export, and no wholesale or demand-response revenue.**

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
