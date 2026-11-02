# M0: data feasibility spike

Date: 2026-11-02. Reproduce with `python spikes/m0_probe.py <empty_dir>` (needs pandas and pyarrow).
Every number below comes from files the probe downloaded. None of it is estimated from documentation.

## TL;DR

| Source | Works? | Notes |
|---|---|---|
| NREL ComStock 2024 release 2 (OEDI S3) | **Yes** | Anonymous HTTPS, no key needed. Real MA building metadata, 15-min timeseries, county weather. |
| OpenEI URDB API | **Blocked** | `api.openei.org` gets a proxy 403 on CONNECT, and `URDB_API_KEY` isn't set. I stopped here, as the brief says. |
| NREL developer API (`developer.nrel.gov`) | Blocked | Not needed for anything in the plan. |

**Recommendation:** use real ComStock data for loads and weather. Don't build a synthetic generator.
Tariffs stay blocked until `api.openei.org` is allowlisted and `URDB_API_KEY` is set.

## 1. ComStock (NREL End-Use Load Profiles)

Base: `s3://oedi-data-lake/nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock/2024/comstock_amy2018_release_2/`
(over HTTPS: `https://oedi-data-lake.s3.amazonaws.com/...`).

### Layout used

| Path | What | Size |
|---|---|---|
| `metadata_and_annual_results/by_state_and_county/full/parquet/state=MA/county=<G25xxxxx>/MA_<county>_baseline.parquet` | Per-building metadata + annual results, 1,101 columns | ~25 MB per county (Middlesex) |
| `.../basic/parquet/...baseline_basic.parquet` | Same rows, 135 columns, but **no peak-demand or utility columns** | ~10 MB per county |
| `timeseries_individual_buildings/by_state/upgrade=0/state=MA/<bldg_id>-0.parquet` | One building, one year, 15-min | 4.8–6.0 MB each; 3,595 files, 15.4 GB in total for MA |
| `weather/amy2018/G25<county>_2018.csv` | Hourly weather for 2018, one file per MA county (14) | ~0.6–0.9 MB each |

`upgrade=0` is the baseline building stock. Upgrades 1–39 are retrofit scenarios that we don't need.

### Timeseries schema (sample `100651-0.parquet`)

- 35,040 rows (365 × 96), 51 columns, indexed by `bldg_id`.
- `timestamp`: `datetime64[ns]`, from `2018-01-01 00:15` to `2019-01-01 00:00`. The stamps look **interval-ending**.
  Timezone handling (local standard time, or with DST) must be confirmed in M1 against the
  ComStock docs before demand windows are applied. **Open item.**
- `out.electricity.total.energy_consumption`: **kWh per 15-min interval**. Average kW = value × 4.
- Plus electricity end-use breakdowns (cooling, fans, lighting, refrigeration, …) and gas and
  district-energy columns. We keep only total electricity.

Sample loads:

| bldg_id | Peak kW | Mean kW | Load factor |
|---|---|---|---|
| 100651 | 288.1 | 156.7 | 0.54 |
| 100652 | 149.7 | 65.9 | 0.44 |

Both are a sensible scale for a 125 kW / 250 kWh battery.

### Metadata (Middlesex County, `G2500170`)

- 35,285 rows but only **2,936 unique `bldg_id`**. Rows are building × census-tract allocations
  with weights, so site selection must de-duplicate on `bldg_id`.
- **949 of the 2,936 were "as simulated" in Connecticut** (`in.as_simulated_state_name`). ComStock
  borrows samples across neighboring states. We should keep only buildings simulated in MA.
- Useful columns: `in.comstock_building_type`, `in.sqft..ft2`, `in.county_name`,
  `in.nhgis_tract_gisjoin`, `in.weather_file_2018`, `out.electricity.total.peak_demand..kw`,
  `out.qoi.maximum_daily_peak_<mon>..kw`, `out.utility_bills.electricity_utility_eia_id`.
- **No latitude/longitude.** The finest location is census tract (a GISJOIN code). The map will need
  tract or county centroids, labeled as approximate.
- Utility EIA IDs in this county (row counts): 11804 (12,031), 4176 (9,656), 54913 (6,088),
  19497 (1,318), 3477 (1,002). I haven't verified which utility each ID is. I'll map them via URDB/EIA once that is
  reachable, rather than guess.

Annual peak demand (kW) by building type, unique buildings, P10 / P50 / P90:

| Type | P10 | P50 | P90 |
|---|---|---|---|
| SmallOffice | 10 | 53 | 140 |
| MediumOffice | 56 | 138 | 361 |
| LargeOffice | 148 | 785 | 2213 |
| RetailStandalone | 13 | 80 | 500 |
| RetailStripmall | 33 | 199 | 765 |
| Warehouse | 9 | 52 | 312 |
| PrimarySchool | 81 | 191 | 301 |
| SecondarySchool | 66 | 343 | 908 |
| Outpatient | 39 | 192 | 431 |
| FullServiceRestaurant | 27 | 96 | 313 |
| QuickServiceRestaurant | 23 | 49 | 88 |
| SmallHotel | 19 | 55 | 158 |
| LargeHotel | 31 | 303 | 1242 |

1,456 of 2,936 buildings have a peak between 100 and 1,000 kW. That is plenty of candidates for 20–50
sites where a 125 kW battery is material.

### Weather

Hourly, 8,760 rows. Columns: `date_time`, dry-bulb °C, RH %, wind speed and direction, GHI, DNI, DHI.
This is enough for M2 imputation features (temperature-driven HVAC load).

### Cache size estimate for M1 (50 sites)

- Timeseries: 50 × ~5.5 MB ≈ 275 MB raw. After keeping only `timestamp` + total electricity
  as parquet, ≈ 50 × ~0.3 MB ≈ 15 MB.
- Metadata: up to 14 × 25 MB = 350 MB raw if all counties are used. Proposal: download, slim to
  ~15 columns, keep the slim file (a few MB), and delete the raw file after slimming. Alternative: select sites from a
  subset of counties, for example 3–4 counties (~100 MB raw).
- Weather: 14 × ~0.7 MB ≈ 10 MB.

Steady-state cache is ≈ 30 MB. Peak transient disk use during fetch is ≈ 400 MB.

## 2. OpenEI Utility Rate Database

- `GET https://api.openei.org/utility_rates?version=8&format=json&sector=Commercial&limit=1` fails with
  `curl: (56) CONNECT tunnel failed, response 403`. The environment's egress proxy denied it.
- `https://openei.org/` is denied the same way.
- `URDB_API_KEY` is not set in the environment.

**Blocked domain: `api.openei.org`.** I did not substitute any other tariff source.

## 3. Representativeness caveats (for LIMITATIONS.md)

- ComStock buildings are **modeled** (EnergyPlus prototypes calibrated to stock-level data), not
  metered sites. Load shapes are smoother and more regular than real meters, so peak-shaving value may
  be over- or under-stated.
- Single weather year (AMY 2018). There is no year-to-year load variability. That has to be an explicit
  uncertainty in M4.
- No coordinates finer than census tract.

## 4. Decisions needed from you

1. **Data source:** confirm real ComStock 2024 release 2 (`upgrade=0`, as-simulated MA only) for loads
   and weather.
2. **Tariffs:** allowlist `api.openei.org` in the environment's network settings and set
   `URDB_API_KEY`. I'm paused on tariffs until then.
3. **Site selection** (my default unless you say otherwise): 40 sites, stratified across 8 building
   types (MediumOffice, RetailStripmall, RetailStandalone, PrimarySchool, SecondarySchool, Outpatient,
   Warehouse, FullServiceRestaurant), annual peak 100–1,000 kW, from 3–4 counties in different
   utility territories, with a fixed seed.

## 5. Out of scope for this spike

ComStock 2025 releases (not checked; 2024 release 2 is complete for our needs) and tract-centroid
coordinates for the map (an M5 concern).
