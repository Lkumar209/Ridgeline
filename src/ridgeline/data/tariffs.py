"""Load tariffs from URDB-format JSON files in `data/tariffs/`.

Files hold OpenEI Utility Rate Database (API v8) records, either a single record or the API's
`{"items": [...]}` envelope, so a live URDB client can be added later without changing the
parser. Anything the bill calculator cannot represent faithfully (tiered rates, per-day fixed
charges, non-kW demand units) is rejected with an error rather than silently simplified.
Demand ratchets are the one documented exception: they are flagged and ignored (LIMITATIONS.md).
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ridgeline.data.schemas import Site, Tariff, TouSchedule


class UnsupportedTariffError(ValueError):
    """The tariff uses a structure Ridgeline does not model."""


def load_tariff_dir(directory: Path) -> list[Tariff]:
    """Parse every `*.json` in `directory`, sorted by filename for stable ordering."""
    tariffs: list[Tariff] = []
    for path in sorted(directory.glob("*.json")):
        tariffs.extend(load_tariff_file(path))
    return tariffs


def load_tariff_file(path: Path) -> list[Tariff]:
    with path.open() as f:
        payload = json.load(f)
    records = payload["items"] if isinstance(payload, dict) and "items" in payload else [payload]
    return [parse_urdb_record(r, fallback_id=path.stem) for r in records]


def parse_urdb_record(record: dict[str, Any], fallback_id: str) -> Tariff:
    """Convert one URDB v8 record into a `Tariff`."""
    flat = _flat_demand(record)
    return Tariff(
        tariff_id=str(record.get("label") or fallback_id),
        utility=str(record["utility"]),
        eiaid=int(record["eiaid"]) if record.get("eiaid") is not None else None,
        name=str(record["name"]),
        source_url=_source_url(record),
        urdb_uri=record.get("uri"),
        effective_date=_epoch_to_date(record.get("startdate")),
        fixed_monthly_usd=_fixed_monthly(record),
        energy_usd_per_kwh=_schedule(record, "energy", required=True),
        demand_tou_usd_per_kw=_schedule(record, "demand", required=False),
        flat_demand_usd_per_kw_by_month=flat,
        min_peak_kw=record.get("peakkwcapacitymin"),
        max_peak_kw=record.get("peakkwcapacitymax"),
        ratchet_ignored=any(float(p) > 0 for p in record.get("demandratchetpercentage") or []),
        is_test_fixture=bool(record.get("ridgeline_test_fixture", False)),
    )


def assign_tariff(site: Site, tariffs: list[Tariff]) -> Tariff | None:
    """The tariff for a site's utility whose size limits include the site's peak.

    Returns None when no tariff matches. Raises if more than one matches, because silently
    picking one would hide a data problem.
    """
    matches = [t for t in tariffs if t.eiaid == site.utility_eiaid and t.is_eligible(site.peak_kw)]
    if len(matches) > 1:
        ids = ", ".join(t.tariff_id for t in matches)
        raise ValueError(f"site {site.site_id} matches several tariffs: {ids}")
    return matches[0] if matches else None


# --- helpers ----------------------------------------------------------------------------


def _source_url(record: dict[str, Any]) -> str:
    for key in ("source", "uri"):
        value = record.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
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


def _schedule(record: dict[str, Any], prefix: str, *, required: bool) -> TouSchedule | None:
    structure = record.get(f"{prefix}ratestructure")
    if not structure:
        if required:
            raise ValueError(f"tariff record has no {prefix}ratestructure")
        return None
    if prefix == "demand":
        _require_kw(record.get("demandunits"))
    return TouSchedule(
        rates=_single_tier_rates(structure, prefix),
        weekday=record[f"{prefix}weekdayschedule"],
        weekend=record[f"{prefix}weekendschedule"],
    )


def _flat_demand(record: dict[str, Any]) -> list[float] | None:
    structure = record.get("flatdemandstructure")
    if not structure:
        return None
    _require_kw(record.get("flatdemandunit"))
    rates = _single_tier_rates(structure, "flat demand")
    months: list[int] = record.get("flatdemandmonths") or [0] * 12
    return [rates[p] for p in months]


def _require_kw(unit: Any) -> None:
    if unit not in (None, "kW"):
        raise UnsupportedTariffError(f"demand unit {unit!r} not supported (need kW)")
