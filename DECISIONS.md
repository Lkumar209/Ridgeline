# Decisions

Short ADR-style records. Each one covers the context, the decision, the alternatives we rejected,
and the consequences. Newest at the bottom.

## ADR-001: Use real NREL ComStock loads, not a synthetic generator (M0)

**Context.** We need 15-min load curves for MA commercial buildings. The M0 spike found ComStock
2024 release 2 on the OEDI public S3 bucket reachable without a key, with MA metadata,
timeseries and county weather (`spikes/m0_data_feasibility.md`).

**Decision.** Use ComStock `comstock_amy2018_release_2`, `upgrade=0` (baseline buildings).

**Rejected.** A synthetic load generator. It would be easier to control but would teach the ranking
nothing about real load shapes. It also needs invented parameters, which runs against principle 2.

**Consequences.** Loads are *modeled* buildings for one weather year (2018), not metered sites
(LIMITATIONS.md). The fetch needs network access to `oedi-data-lake.s3.amazonaws.com`. Tests
use small committed fixtures, so they run offline.

## ADR-002: Tooling and dependencies (M1)

`uv` for environments and the lockfile. `ruff` for lint and format. `mypy --strict` on the whole
package. `pytest` and `hypothesis` for tests. Runtime dependencies, each with a reason:

| Dependency | Why |
|---|---|
| numpy, pandas | Interval time series and vectorized math. The standard choice, and reviewers know them. |
| pyarrow | ComStock ships parquet. |
| pydantic | Validated models at module boundaries (`data/schemas.py`) and for config. |
| pyyaml | `config/default.yaml` and `assumptions.yaml` are human-edited YAML. |
| typer | Small typed CLI with no boilerplate. |
| httpx | Streaming downloads with timeouts. |

**Rejected.** polars or duckdb (faster, but nothing here needs it, and they are less familiar to a new
teammate), and requests (httpx covers the same ground). Later milestones add scipy (M3 LP bound),
matplotlib (M2 plots), fastapi (M5) and anthropic (M6), each justified when it is added.

## ADR-003: Timestamp convention, standard time and interval-ending (M1)

**Context.** Demand charges apply in wall-clock windows (for example weekdays 8:00–20:00 local).
A one-hour error would shift every on-peak window for the seven months of daylight saving.

**Evidence (real data):**
1. Raw ComStock stamps are a perfectly regular 35,040-row year from `2018-01-01 00:15` to
   `2019-01-01 00:00`. Local prevailing time would have a 23-hour day in March and a 25-hour day in
   November. So the stamps are in a fixed-offset zone and mark the interval *end*.
2. Weather GHI peaks at the 12:00 hour-ending stamp in both January and July. That is solar noon in
   standard time (about 11:45 EST in Boston), not UTC.
3. In five buildings, the weekday lighting schedule runs exactly 1 h *earlier* in raw stamps during
   EDT than during EST. Building schedules follow daylight saving and the timestamps don't.

**Decision.** Treat source stamps as naive UTC-5, interval-ending. Convert once at load time to
UTC interval-start (`data/timestamps.py`). Apply tariff windows after converting to
`America/New_York`.

**Tests.** `tests/unit/test_timestamps.py` pins the pure conversion: 92 intervals on the March DST
day, 100 on the November one, and a July stamp landing an hour later on the wall clock. It also
checks on real fixture data that the lighting schedule lines up on the same wall-clock time in
February and July after conversion, but is 1 h apart before it.

## ADR-004: Site selection (M1)

**Decision.** 40 sites: 8 building types × 5. Annual 15-min peak between 100 and 1,000 kW. Within each type,
2/1/2 sites come from the low/mid/high tercile of the peak-to-average ratio (PAR), drawn with
seed `20261102`. Low-PAR (flat) sites are included on purpose, as likely weak candidates, so the
ranking has spread. Only buildings simulated in MA are used. Sites are limited to utilities
EIA 11804 and 54913, which serve about 72% of screened candidates, so two utilities' tariffs cover every site.
Counties are Middlesex, Worcester, Suffolk and Hampden (Boston area, central and western MA).
A 10-site dev subset is the first two rounds of a round-robin over types, with each type's PAR
tier rotated so the subset mixes tiers.

**Context worth knowing.** ComStock *allocates* each sampled building to several counties and
tracts by weight (on average about 7 counties per building). A building's "county" here is its
highest-weight allocation among the four study counties, not a street address. Utility is a fixed
attribute of each building and doesn't depend on the allocation, so county and utility territory
are not guaranteed to agree with real geography.

**Rejected.** Pure random sampling, which over-weights high-PAR retail and gives no
guaranteed spread. Choosing sites by hand, which isn't reproducible and invites cherry-picking.

**Consequence.** The utility mix is uneven: 35 sites for 11804 and 5 for 54913. That reflects the
candidate pool (about 72/28) plus sampling noise.

## ADR-005: Tariffs from URDB-format JSON files; refuse what we can't model (M1)

**Context.** The URDB API is blocked in the dev environment (`api.openei.org`). The project owner
will commit 2–3 real tariff files.

**Decision.** `data/tariffs/*.json` holds URDB API v8 records (a single record or the
`{"items": [...]}` envelope), so a live URDB client can be added later without touching the
parser. Sites are matched to tariffs by `eiaid` and the tariff's kW eligibility limits. More than one
match is an error. The parser *rejects* tiered rates, per-day fixed charges and non-kW demand
units instead of approximating them. Demand ratchets are flagged (`ratchet_ignored`) and ignored,
and LIMITATIONS.md says so.

**Rejected.** Hand-entering rate values in YAML, which is easy to mistype, has no provenance,
and doesn't match URDB.

## ADR-006: Branch workflow in a pinned cloud session (M0)

The cloud session can push only `claude/dazzling-cori-pty3ol`. Each milestone is one PR from that
branch into `main`. After a merge, the branch restarts from the new `main`.
