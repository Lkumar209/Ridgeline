# M2: meter gaps and imputation

**Question.** Utility interval data often has 1–3 month holes. If we fill them, how wrong are the
filled months? And how wrong is the thing we actually bill on, each month's peak kW?

**Answer (illustrative, ComStock modeled buildings, current 40-site list).** A simple
seasonal-profile fill understates billing peaks: in half the affected months it is off by 13% or
more, and its average bias is −14%. The bias is worst in summer. A weather-aware regression roughly
halves the typical peak error (7%) and cuts the bias to about −3%. The tail is still fat: with
the regression, 1 month in 10 is off by 25% or more. That spread is what M4 should carry as
uncertainty for any site with imputed months.

## Setup

- **Data:** all 40 sites in `data/sites.csv` (after the M3 NSTAR replacement, ADR-010), one real
  ComStock year each (15-min, AMY2018).
- **Gaps:** 6 per site, seeded (`gaps.seed = 7`). Lengths are 30–92 days (mean 62), and they start at a
  random 15-min interval. That makes 240 gaps, and 497 billing months that are at least 50% inside a gap.
- **Scoring:** the true data is hidden, each method fills it, and we compare against the truth.
- **Reproduce:** `uv run ridgeline fetch-data && uv run python scripts/evaluate_imputation.py &&
  uv run python scripts/plot_imputation.py`. The experiment takes about 65 s for 40 sites, or
  `--dev-subset` scores the 10 dev sites.

## Methods

| Method | What it does | Why |
|---|---|---|
| `seasonal_profile` (baseline) | For each gap, average the site's own load by (weekday/weekend, 15-min slot) over the 28 days before and after, and repeat that profile. | It is the obvious first thing anyone would do, and fully explainable. |
| `regression_weather` | Ridge least squares fit on the site's observed months: 192 (weekday/weekend × 15-min slot) dummies, plus cooling and heating degree terms (18 °C / 10 °C hinges), plain and × occupied hours. | Adds what the baseline can't see: temperature-driven HVAC load. |
| `regression_weather_peers` | The same, plus one column: the mean normalized load of the other same-type sites at the same instant. | "Similar sites", which can capture shared weather and schedule effects that the degree terms miss. |

All of these are plain numpy with no ML dependency (DECISIONS.md ADR-007).

## Results

All 240 gaps. Peak metrics use months at least 50% inside a gap. Signed error = imputed − actual.

| Method | MAE (kW, median) | MAPE (%, median) | Peak abs error (%, median) | Peak abs error (%, P90) | Peak bias (%, mean) |
|---|---|---|---|---|---|
| seasonal_profile | 9.4 | 16.0 | 13.3 | 39.0 | −14.3 |
| regression_weather | 8.3 | 16.1 | 7.3 | 25.2 | −3.4 |
| regression_weather_peers | 7.2 | 13.9 | 5.3 | 22.7 | −1.1 |

![Billing-peak error by method](m2/monthly_peak_error.png)

**MAPE cannot tell the methods apart; the billing peak can.** The regression's MAPE (16.1%) is
no better than the baseline's (16.0%), yet its billing-peak error is about half. A method
chosen by MAPE alone would look as good as the others and still be wrong where the money is.

**The baseline underestimates peaks, and summer is where it hurts.**

| Months | Baseline | Regression | Regression + peers |
|---|---|---|---|
| Summer (Jun–Sep), abs error % median | 18.8 | 8.1 | 4.5 |
| Summer, mean bias % | −19.4 | −4.0 | −0.5 |
| Other months, abs error % median | 10.0 | 6.5 | 5.6 |
| Other months, mean bias % | −10.8 | −2.9 | −1.5 |

A summer gap gets filled with May and September days, so cooling peaks vanish (see the example
below). Peak shaving is worth the most in exactly those months.

![One week inside a simulated summer outage](m2/example_summer_gap.png)

**By building type** (peak abs error %, median):

| Type | Baseline | Regression | + peers |
|---|---|---|---|
| Warehouse | 4.4 | 3.8 | 2.7 |
| FullServiceRestaurant | 10.7 | 4.7 | 2.5 |
| Outpatient | 15.0 | 5.7 | 5.5 |
| MediumOffice | 9.3 | 6.5 | 3.4 |
| RetailStandalone | 13.5 | 8.3 | 6.7 |
| SecondarySchool | 23.5 | 11.1 | 7.6 |
| RetailStripmall | 15.4 | 14.0 | 11.0 |
| PrimarySchool | 24.3 | 14.8 | 7.8 |

Schools are hardest: summer break and the academic calendar are not in the features. Peers help
most there, because the peer schools share the calendar.

## What this means for demand charges

- The error flows straight into the bill. A demand charge is `rate × monthly peak kW`, so a −14%
  peak bias means the baseline understates that month's demand charge by about 14%. It also
  understates the battery's shaving opportunity in that month. The median absolute miss is 18.5 kW
  (baseline) against 11.9 kW (regression), next to a 125 kW battery.
- **In dollars:** at MECo G-2's $14.82/kW (`data/tariffs/meco_g2_sema.json`), the median miss is about
  $274 per affected month for the baseline and $176 for the regression.
- **Uncertainty to carry forward:** the signed peak error of `regression_weather` has P10/P90 of
  −20.6% / +11.7% per affected month. Any site with imputed months should carry this into M4
  rather than treat filled data as known. The current 40 sites have no real gaps.

## Choice and caveats

- **Default imputer: `regression_weather`.** On this site list the peer variant beats it on every
  breakdown above, by type, by season and on bias. We still don't make it the default, because its
  advantage is probably *inflated*: ComStock buildings of one type share prototype schedules, so
  peers move together far more tightly than real neighbors (LIMITATIONS.md). The peer variant
  stays available, and we can revisit it on real meter data.
- **Resolution is a trade-off, not a free win.** On these 40 sites we compared hourly against
  15-min time dummies:
  - 15-min slots, which match the data, cut the peak bias from −5.4% to −3.4% (regression) and from
    −2.5% to −1.1% (peers), and lower MAE and MAPE.
  - They slightly widen the spread: median abs peak error 7.1% → 7.3% (regression) and 4.3% →
    5.3% (peers).
  - We keep 15-min slots because a systematic understatement of demand charges is the costlier
    error for ranking. Hourly numbers come from a scratch rerun, not committed code.
- **Clean gaps only.** Gaps here are whole-meter outages in otherwise clean modeled data. Real
  outages may cluster (storms), come with partial data, or affect peers at the same time.
- **Calendar months** stand in for billing cycles.
