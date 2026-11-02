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

## Not modeled (by design, per the brief)
- Wholesale market, capacity or demand-response revenue.
- Interconnection costs and timelines.
- Incentive program details beyond what `assumptions.yaml` states with a source.
