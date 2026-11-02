# Tariff files

Put one JSON file per tariff here. Each holds an OpenEI Utility Rate Database (URDB) API v8
record, either a single record or the API's `{"items": [ ... ]}` response.

Required fields: `utility`, `eiaid`, `name`, a `source` (the utility's tariff document URL) or
`uri` (the URDB page), `energyratestructure` with `energyweekdayschedule` and
`energyweekendschedule`, and at least one demand charge (`demandratestructure` with its schedules,
or `flatdemandstructure` with `flatdemandmonths`). Optional fields: `peakkwcapacitymin` and
`peakkwcapacitymax`, which decide which sites the tariff applies to, plus
`fixedchargefirstmeter`/`fixedchargeunits` and `startdate`.

The loader refuses tiered rates, per-day fixed charges and non-kW demand units instead of
approximating them (DECISIONS.md ADR-005). `uv run pytest tests/unit/test_tariffs.py` checks that
every file here parses.

Sites are matched to a tariff by `eiaid` plus the kW limits. Exactly one tariff should match each
site. `uv run ridgeline fetch-data` prints how many sites are covered.
