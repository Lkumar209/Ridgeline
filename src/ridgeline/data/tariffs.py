"""Load tariffs from URDB-format JSON files in `data/tariffs/` and match them to sites.

Files hold OpenEI Utility Rate Database (API v8) records, either a single record or the API's
`{"items": [...]}` envelope, so a live URDB client can be added later without changing the
parser. Anything the bill calculator cannot represent faithfully (tiered rates, per-day fixed
charges, unknown demand units) is rejected with an error rather than silently simplified.

Two documented exceptions:
* demand ratchets are flagged and ignored (LIMITATIONS.md);
* $/kVA demand charges are converted to $/kW with an assumed power factor taken from
  `assumptions.yaml` (`power_factor_for_kva_demand`), and the tariff records the PF used.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ridgeline.data.schemas import Site, Tariff, TouSchedule


class UnsupportedTariffError(ValueError):
    """The tariff uses a structure Ridgeline does not model."""


class TariffMatchError(ValueError):
    """A site matched zero tariffs, or more than one."""


def load_tariff_dir(directory: Path, power_factor: float | None = None) -> list[Tariff]:
    """Parse every `*.json` in `directory`, sorted by filename for stable ordering."""
    tariffs: list[Tariff] = []
    for path in sorted(directory.glob("*.json")):
        tariffs.extend(load_tariff_file(path, power_factor))
    return tariffs


def load_tariff_file(path: Path, power_factor: float | None = None) -> list[Tariff]:
    with path.open() as f:
        payload = json.load(f)
    records = payload["items"] if isinstance(payload, dict) and "items" in payload else [payload]
    return [parse_urdb_record(r, path.stem, power_factor) for r in records]


def parse_urdb_record(
    record: dict[str, Any], fallback_id: str, power_factor: float | None = None
) -> Tariff:
    """Convert one URDB v8 record into a `Tariff`.

    `power_factor` is required only if the record bills demand in kVA; without it such a
    record is refused.
    """
    demand_unit = _demand_unit(record)
    divisor = 1.0
    if demand_unit == "kVA":
        if power_factor is None:
            raise UnsupportedTariffError("demand billed in kVA but no power factor was given")
        divisor = power_factor
    return Tariff(
        tariff_id=str(record.get("label") or fallback_id),
        utility=str(record["utility"]),
        eiaid=int(record["eiaid"]) if record.get("eiaid") is not None else None,
        name=str(record["name"]),
        source_urls=_source_urls(record),
        urdb_uri=record.get("uri"),
        effective_date=_epoch_to_date(record.get("startdate")),
        fixed_monthly_usd=_fixed_monthly(record),
        energy_usd_per_kwh=_schedule(record, "energy", required=True),
        demand_tou_usd_per_kw=_schedule(record, "demand", required=False, divisor=divisor),
        flat_demand_usd_per_kw_by_month=_flat_demand(record, divisor),
        min_peak_kw=record.get("peakkwcapacitymin"),
        max_peak_kw=record.get("peakkwcapacitymax"),
        min_monthly_kwh=record.get("peakkwhusagemin"),
        max_monthly_kwh=record.get("peakkwhusagemax"),
        ratchet_ignored=any(float(p) > 0 for p in record.get("demandratchetpercentage") or []),
        demand_converted_from_kva_at_pf=power_factor if demand_unit == "kVA" else None,
        is_test_fixture=bool(record.get("ridgeline_test_fixture", False)),
    )


# --- matching ---------------------------------------------------------------------------


def eligible_tariffs(site: Site, tariffs: list[Tariff]) -> list[Tariff]:
    """Tariffs for the site's utility whose limits include the site's pre-battery annual peak
    and its average monthly usage (DECISIONS.md ADR-009)."""
    return [
        t
        for t in tariffs
        if t.eiaid == site.utility_eiaid and t.is_eligible(site.peak_kw, site.mean_monthly_kwh)
    ]


def match_tariff(site: Site, tariffs: list[Tariff]) -> Tariff:
    """The single tariff for a site. Raises `TariffMatchError` on zero or several matches."""
    matches = eligible_tariffs(site, tariffs)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise TariffMatchError(
            f"site {site.site_id} (EIA {site.utility_eiaid}, peak {site.peak_kw:.0f} kW, "
            f"{site.mean_monthly_kwh:,.0f} kWh/month) matches no tariff"
        )
    ids = ", ".join(t.tariff_id for t in matches)
    raise TariffMatchError(f"site {site.site_id} matches several tariffs: {ids}")


@dataclass(frozen=True)
class TariffCoverage:
    matched: dict[str, str] = field(default_factory=dict)  # site_id -> tariff_id
    unmatched: list[str] = field(default_factory=list)
    ambiguous: dict[str, list[str]] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return not self.unmatched and not self.ambiguous


def tariff_coverage(sites: list[Site], tariffs: list[Tariff]) -> TariffCoverage:
    """Which sites match exactly one tariff, none, or several (for reporting, not billing)."""
    coverage = TariffCoverage()
    for site in sites:
        matches = eligible_tariffs(site, tariffs)
        if len(matches) == 1:
            coverage.matched[site.site_id] = matches[0].tariff_id
        elif not matches:
            coverage.unmatched.append(site.site_id)
        else:
            coverage.ambiguous[site.site_id] = [t.tariff_id for t in matches]
    return coverage


# --- helpers ----------------------------------------------------------------------------


def _source_urls(record: dict[str, Any]) -> list[str]:
    """Every URL in `source` (URDB often lists several, separated by blank lines), else `uri`.

    Regression: a multi-URL `source` used to be passed whole to HttpUrl, which stripped the
    whitespace and silently glued the URLs into one invalid link.
    """
    for key in ("source", "uri"):
        value = record.get(key)
        if isinstance(value, str):
            urls = [token for token in value.split() if token.startswith("http")]
            if urls:
                return urls
    raise ValueError("tariff record needs a 'source' or 'uri' URL")


def _epoch_to_date(value: Any) -> date | None:
    if value is None:
        return None
    return datetime.fromtimestamp(int(value), tz=UTC).date()


def _fixed_monthly(record: dict[str, Any]) -> float:
    amount = float(record.get("fixedchargefirstmeter") or 0.0)
    units = record.get("fixedchargeunits", "$/month")
    if amount and units != "$/month":
        raise UnsupportedTariffError(f"fixed charge units {units!r} not supported")
    return amount


def _single_tier_rates(structure: list[list[dict[str, Any]]], what: str) -> list[float]:
    rates = []
    for period, tiers in enumerate(structure):
        if len(tiers) != 1:
            raise UnsupportedTariffError(f"{what} period {period} has {len(tiers)} tiers")
        tier = tiers[0]
        rates.append(float(tier.get("rate", 0.0)) + float(tier.get("adj", 0.0)))
    return rates


def _demand_unit(record: dict[str, Any]) -> str:
    """The single demand unit used by the record: "kW" or "kVA". Refuses anything else."""
    units = set()
    if record.get("demandratestructure"):
        units.add(record.get("demandunits") or "kW")
    if record.get("flatdemandstructure"):
        units.add(record.get("flatdemandunit") or "kW")
    unknown = units - {"kW", "kVA"}
    if unknown:
        raise UnsupportedTariffError(
            f"demand unit {sorted(unknown)} not supported (need kW or kVA)"
        )
    if len(units) > 1:
        raise UnsupportedTariffError("mixed kW and kVA demand charges are not supported")
    return units.pop() if units else "kW"


def _schedule(
    record: dict[str, Any], prefix: str, *, required: bool, divisor: float = 1.0
) -> TouSchedule | None:
    structure = record.get(f"{prefix}ratestructure")
    if not structure:
        if required:
            raise ValueError(f"tariff record has no {prefix}ratestructure")
        return None
    return TouSchedule(
        rates=[r / divisor for r in _single_tier_rates(structure, prefix)],
        weekday=record[f"{prefix}weekdayschedule"],
        weekend=record[f"{prefix}weekendschedule"],
    )


def _flat_demand(record: dict[str, Any], divisor: float) -> list[float] | None:
    structure = record.get("flatdemandstructure")
    if not structure:
        return None
    rates = _single_tier_rates(structure, "flat demand")
    months: list[int] = record.get("flatdemandmonths") or [0] * 12
    return [rates[p] / divisor for p in months]
