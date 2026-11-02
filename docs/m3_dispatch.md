# M3: battery dispatch and billing

**Status.** Dispatch, billing and the perfect-foresight bound are done and property-tested.
Results use the real MECo G-2 delivery tariff (URDB `67d08dea7568c8189f03c54e`), with a
labeled proxy for sites above its 200 kW cap (ADR-010). All outputs are illustrative.

## What runs

`uv run ridgeline simulate [--dev-subset] [--tariff-override FILE] [--wraparound-lookahead]`

For each site and each local calendar month, four strategies are run:

| Strategy | What it knows | Role |
|---|---|---|
| `base` | — | No battery |
| `practical` | History only: starts at the lowest threshold it could have held *last* month, then ratchets up if breached. The first month has no history, so it stays idle. | The controller we would actually run |
| `oracle` | This month's lowest holdable threshold | Diagnostic: separates "bad rule" from "bad forecast" |
| `optimal` | The whole month in advance; LP minimizing the bill | Upper bound (`battery/optimal.py`, scipy HiGHS) |

**Battery model:** 125 kW / 250 kWh, RTE 0.88 split evenly between charge and discharge, SoC between
5% and 95%, starting full each month (all values in `assumptions.yaml`, all ASSUMPTION).

**Billing:** monthly energy, flat demand, TOU demand and fixed charges, with rates looked up in local
wall-clock time. A hand-computed golden bill pins it.

**Never worse than no battery:** a month whose dispatch would cost more than no battery is billed
idle and flagged.

## Guarantees (property tests, `tests/property/test_battery_props.py`)

For random loads, battery sizes, efficiencies and thresholds:

- State of charge stays within `[soc_min, soc_max]`.
- Energy is conserved with losses: Δstored = η_c·E_in − E_out/η_d, and losses are ≥ 0.
- Power stays within limits; there is no export; the threshold rule never charges and discharges at once.
- The battery never raises the billing peak, under every strategy.
- The bill with a battery is ≤ the bill without, every month, every strategy.
- The LP bill is ≤ every controller's bill.

## Dev-subset results on MECo G-2

These are annual **delivery** bills only (supply excluded, `bill_scope_delivery_only`), so the
percentages overstate the share of a full bill. Proxy rows apply G-2 beyond its eligibility
(ASSUMPTION). Raw numbers: `docs/m3/dev_subset_g2_summary.csv`.

| Site | Type | Peak kW | Tariff | Delivery bill $ | Practical savings $ | Optimal savings $ | Capture |
|---|---|---|---|---|---|---|---|
| cs-16342 | RetailStandalone | 176 | G-2 | 35,540 | 6,391 | 9,880 | 0.65 |
| cs-130562 | Outpatient | 134 | G-2 | 36,789 | 4,932 | 7,737 | 0.64 |
| cs-31197 | Warehouse | 185 | G-2 | 86,298 | 2,444 | 4,560 | 0.54 |
| cs-9978 | RetailStripmall | 133 | G-2 | 39,443 | 2,583 | 5,265 | 0.49 |
| cs-65325 | FullServiceRestaurant | 136 | G-2 | 42,708 | 2,264 | 5,910 | 0.38 |
| cs-45533 | PrimarySchool | 138 | G-2 | 34,166 | 1,631 | 5,896 | 0.28 |
| cs-32304 | MediumOffice | 205 | proxy | 70,024 | 5,424 | 9,051 | 0.60 |
| cs-30878 | RetailStripmall | 204 | proxy | 40,027 | 5,828 | 10,551 | 0.55 |
| cs-68361 | MediumOffice | 275 | proxy | 116,435 | 2,857 | 6,276 | 0.46 |
| cs-144167 | SecondarySchool | 566 | proxy | 132,055 | 5,369 | 12,870 | 0.42 |

- **Median capture:** 0.51 for the practical controller. The oracle-threshold rule gets about 97% of the LP's
  savings (it cuts the same peak; the LP also avoids some round-trip losses). The gap is forecasting
  the threshold, not the rule.
- **Idle months:** 6 of 120 site-months are billed idle (practical). The inherited threshold was too low
  for a hotter or busier month, the battery drained early, the peak ratcheted back to the
  no-battery level, and recharge losses would have made the month slightly worse.
- **Schools capture least** (0.28, 0.42). Academic-calendar transitions break month-to-month persistence.
- **Runtime:** about 8 s per site-year with the LP (10 dev sites in 78 s). M4 should reuse each site's
  simulated savings rather than re-simulate per Monte Carlo draw.

## January lookahead: removed

The practical controller used to seed January's threshold from December of the *same* data year,
which is future information. Now the first month has no history and the battery stays idle
(`practical_no_history`). The old behavior is only available as `--wraparound-lookahead`, and outputs
flag it (`practical_history_is_lookahead`).

On the original dev subset (flat-demand fake tariff), median capture went from **0.565 to 0.544**.
The 57% previously reported was about 2 points high. The biggest drops were at the school (0.32 to
0.27) and offices with high January peaks. Both numbers come from the same sites and the same tariff,
so the difference is the lookahead alone.

## Tariff coverage

| | Real G-2 | G-2 proxy (> 200 kW) | Unmatched |
|---|---|---|---|
| All 40 sites | 17 | 23 | 0 |
| Dev subset (10) | 6 | 4 | 0 |

- **Before the decision:** under G-2 alone, coverage was 13/40 and 4/10. The project owner chose to proxy
  11804 sites above 200 kW and to replace the 5 NSTAR sites with same-stratum 11804 sites (ADR-010).
- **Usage eligibility** uses average monthly use, per the tariff's own wording ("average use will
  exceed 10,000 kWh/month").
- **Fails loudly:** without tariff files, or for any site matching zero or several tariffs,
  `ridgeline simulate` exits non-zero and lists every failing site.
