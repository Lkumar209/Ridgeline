# M3: battery dispatch and billing

**Status.** The dispatch, billing and optimization code is done and property-tested. **No real
tariff is committed yet**, so every dollar figure here comes from the *fake* test fixture
(`tests/fixtures/tariff_test_fixture.json`) and means nothing in absolute terms. The kW results
and the controller-vs-optimum *ratios* are structural and do carry over.

## What runs

`uv run ridgeline simulate [--dev-subset] [--tariff-override FILE] [--no-optimal]`

For each site and each local calendar month, four strategies are run:

| Strategy | What it knows | Role |
|---|---|---|
| `base` | — | No battery |
| `practical` | Only history: starts at the lowest threshold it could have held *last* month, then ratchets up if breached | The controller we would actually run |
| `oracle` | This month's lowest holdable threshold (foresight about the threshold only) | Diagnostic: separates "bad rule" from "bad forecast" |
| `optimal` | The whole month in advance; LP over charge, discharge and SoC that minimizes the bill | Upper bound (`battery/optimal.py`, scipy HiGHS) |

**Battery model:** 125 kW / 250 kWh, RTE 0.88 split evenly between charge and discharge, SoC between
5% and 95%, starting full each month (all values in `assumptions.yaml`, all ASSUMPTION).

**Billing:** monthly energy, flat demand, TOU demand and fixed charges, with rates looked up in local
wall-clock time (`battery/billing.py`). A hand-computed golden bill pins it.

**Never worse than no battery:** if a month's dispatch would cost more than no battery
(losses outweighing demand savings), that month is billed idle and flagged. The operator can always
leave the battery off.

## Guarantees (property tests, `tests/property/test_battery_props.py`)

For random loads, battery sizes, efficiencies and thresholds:

- State of charge stays within `[soc_min, soc_max]`.
- Energy is conserved with losses: Δstored = η_c·E_in − E_out/η_d, and losses are ≥ 0.
- Power stays within limits; there is no export; the threshold rule never charges and discharges at once.
- The battery never raises the billing peak, under every strategy.
- The bill with a battery is ≤ the bill without, every month, every strategy.
- The LP bill is ≤ every controller's bill, so the optimum really is an upper bound on savings.

## Dev-subset results (fake tariff; ratios and kW only)

Using a flat-demand-only variant of the fake fixture, which has the same structure as MECo G-2:

| Site | Type | Mean monthly peak cut, practical (kW) | Oracle (kW) | Optimal (kW) | Capture ratio (practical / optimal savings) |
|---|---|---|---|---|---|
| cs-68361 | MediumOffice | 18.0 | 34.5 | 34.5 | 0.49 |
| cs-38821 | RetailStripmall | 22.7 | 37.5 | 37.5 | 0.57 |
| cs-16342 | RetailStandalone | 36.6 | 55.2 | 55.2 | 0.64 |
| cs-45533 | PrimarySchool | 11.1 | 32.5 | 32.5 | 0.32 |
| cs-144167 | SecondarySchool | 32.2 | 71.6 | 71.6 | 0.43 |
| cs-130562 | Outpatient | 28.2 | 43.3 | 43.3 | 0.62 |
| cs-31197 | Warehouse | 16.1 | 26.6 | 26.6 | 0.55 |
| cs-42670 | FullServiceRestaurant | 21.7 | 36.8 | 36.8 | 0.56 |
| cs-32304 | MediumOffice | 35.1 | 51.1 | 51.1 | 0.66 |
| cs-30878 | RetailStripmall | 36.9 | 59.3 | 59.3 | 0.61 |

**The practical-vs-optimal gap is the forecast, not the rule.** With the right threshold, the
simple threshold rule cuts exactly as much peak as the LP (within 0.01 kW) and gets a median 95%
of its savings; the rest is round-trip losses the LP avoids. The practical controller's median
capture is 57%. Its weakness is the persistence threshold: entering July with June's threshold, the
battery drains on the first hot afternoon and the month's peak ratchets up. Schools are worst
(0.32), because their summer and academic-year months differ sharply.

Under the full fake fixture (TOU energy and TOU demand), the capture ratios fall to 0.21–0.50.
Part of that is energy arbitrage the LP exploits and the threshold rule ignores by design.

**Runtime:** about 6–7 s per site-year with the LP (10 dev sites in 67 s). M4 should reuse each
site's simulated annual savings rather than re-simulate per Monte Carlo draw.

## Tariff coverage (MECo G-2 limits: EIA 11804, ≤ 200 kW, ≥ 10,000 kWh/month)

| | Matched | Unmatched | 11804 above 200 kW | 54913 (no usable tariff) | Below usage minimum |
|---|---|---|---|---|---|
| All 40 sites | **13** | 27 | 22 | 5 | 0 |
| Dev subset (10) | **4** | 6 | 4 | 2 | 0 |

- **Usage minimum:** it is checked against average monthly kWh (the lowest site averages 19,738
  kWh/month). Under a stricter "every month ≥ 10,000 kWh" reading, cs-16342 (RetailStandalone, one month at
  6,585 kWh) would also drop out, giving 12/40 and 3/10.
- **Just over the line:** two dev sites, cs-32304 (205 kW) and cs-30878 (204 kW), miss the 200 kW cap by
  under 3%.
- **Fails loudly:** `ridgeline simulate` without `--tariff-override` exits non-zero and lists every
  unmatched site with its utility, peak and usage.

### Options for the unmatched sites (decision pending)

| Option | What changes | Pros | Cons |
|---|---|---|---|
| **A. Restrict to covered sites** | Re-select all 40 from EIA 11804 buildings with peak 100–200 kW (or keep only the 13) | Every number traces to a real tariff | Narrow range: a 125 kW battery against a 100–200 kW peak is huge, so results skew to "battery oversized"; fewer building types have enough candidates; loses the large-site story |
| **B. Labeled proxy for > 200 kW** | Apply the G-2 values to > 200 kW 11804 sites, marked ASSUMPTION ("G-2 applied beyond its eligibility") | No invented numbers; keeps all 35 sites on 11804; easy to swap out | Real large-customer rates (G-3) are TOU with different demand charges, so savings for big sites are only indicative |
| **C. Find better rates** | You locate a secondary-voltage MECo G-3 (> 200 kW) record and a usable NSTAR record | Most faithful | Uncertain availability (you found only 115 kV G-3 and kVA/expired NSTAR records) |

**Recommendation: B now for 11804, C in parallel, and drop the 5 NSTAR (54913) sites for now.**
- **B for 11804** keeps the site mix and the ranking spread while using only real numbers. The proxy
  is visible in every output and in LIMITATIONS.md, and it is one file to replace when C succeeds.
- **Dropping NSTAR:** proxying them with a different utility's tariff stretches too far. They would be
  replaced from the 11804 pool with the same type and PAR tier, keeping 40 sites.
- **Not changed yet:** the site list and the tariff files stay as they are until you decide.
