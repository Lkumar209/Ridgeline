# Tariff files

Put one JSON file per tariff here. Each holds an OpenEI Utility Rate Database (URDB) API v8
record, either a single record or the API's `{"items": [ ... ]}` response.

**Required fields:** `utility`, `eiaid`, `name`, a `source` (the utility's tariff document URL)
or `uri` (the URDB page), `energyratestructure` with `energyweekdayschedule` and
`energyweekendschedule`, and at least one demand charge: either `demandratestructure` with its
schedules, or `flatdemandstructure` with `flatdemandmonths`.

**Eligibility (optional):** `peakkwcapacitymin`/`peakkwcapacitymax` (kW) and
`peakkwhusagemin`/`peakkwhusagemax` (kWh per month). A site must satisfy both, using its annual
15-min peak and its average monthly kWh (DECISIONS.md ADR-009).

**Other optional fields:** `fixedchargefirstmeter`/`fixedchargeunits`, `startdate`,
`demandratchetpercentage`.

**What the loader refuses** rather than approximates (DECISIONS.md ADR-005):
- tiered rates;
- per-day fixed charges;
- demand units other than kW or kVA;
- mixed kW and kVA.

Demand billed in kVA is converted to $/kW as rate / PF, using `power_factor_for_kva_demand`
(an ASSUMPTION in `assumptions.yaml`).

**Matching:** sites are matched by `eiaid` plus the limits above. Exactly one tariff must match
each site; zero or several matches raise `TariffMatchError`.

**Checks:**
- `uv run pytest tests/unit/test_tariffs.py` checks that every file here parses.
- `uv run ridgeline fetch-data` prints coverage.
