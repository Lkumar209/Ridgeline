from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from ridgeline.data.schemas import Site
from ridgeline.data.tariffs import (
    UnsupportedTariffError,
    assign_tariff,
    load_tariff_dir,
    load_tariff_file,
    parse_urdb_record,
)


@pytest.fixture
def record(tariff_fixture_path: Path) -> dict[str, Any]:
    with tariff_fixture_path.open() as f:
        items: list[dict[str, Any]] = json.load(f)["items"]
    return copy.deepcopy(items[0])


def _site(peak_kw: float = 300.0, eiaid: int = 99999) -> Site:
    return Site(
        site_id="cs-1",
        bldg_id=1,
        building_type="MediumOffice",
        county_gisjoin="G2500170",
        county_name="MA, Middlesex County",
        tract_gisjoin="T",
        utility_eiaid=eiaid,
        sqft=1000.0,
        peak_kw=peak_kw,
        mean_kw=100.0,
        par_tier="mid",
        dev_subset=False,
    )


def test_fixture_parses_and_is_marked_as_test_data(tariff_fixture_path: Path) -> None:
    (tariff,) = load_tariff_file(tariff_fixture_path)
    assert tariff.is_test_fixture
    assert tariff.tariff_id == "TEST-FIXTURE-TOU"
    assert tariff.fixed_monthly_usd == 100.0
    assert tariff.effective_date is not None and tariff.effective_date.year == 2018


def test_energy_rate_includes_adjustment(record: dict[str, Any]) -> None:
    tariff = parse_urdb_record(record, "x")
    assert tariff.energy_usd_per_kwh.rate_at(month=1, hour=12, is_weekend=False) == 0.20
    assert tariff.energy_usd_per_kwh.rate_at(month=1, hour=12, is_weekend=True) == 0.10
    assert tariff.energy_usd_per_kwh.rate_at(month=1, hour=7, is_weekend=False) == 0.10


def test_flat_demand_expands_to_twelve_months(record: dict[str, Any]) -> None:
    flat = parse_urdb_record(record, "x").flat_demand_usd_per_kw_by_month
    assert flat == [10.0] * 5 + [12.0] * 4 + [10.0] * 3


def test_tou_demand_parsed(record: dict[str, Any]) -> None:
    demand = parse_urdb_record(record, "x").demand_tou_usd_per_kw
    assert demand is not None
    assert demand.rate_at(month=7, hour=15, is_weekend=False) == 5.0


def test_tiered_rates_are_refused(record: dict[str, Any]) -> None:
    record["energyratestructure"][0].append({"rate": 0.2, "max": 1000})
    with pytest.raises(UnsupportedTariffError, match="tiers"):
        parse_urdb_record(record, "x")


def test_per_day_fixed_charge_is_refused(record: dict[str, Any]) -> None:
    record["fixedchargeunits"] = "$/day"
    with pytest.raises(UnsupportedTariffError, match="fixed charge"):
        parse_urdb_record(record, "x")


def test_non_kw_demand_unit_is_refused(record: dict[str, Any]) -> None:
    record["demandunits"] = "kVA"
    with pytest.raises(UnsupportedTariffError, match="kVA"):
        parse_urdb_record(record, "x")


def test_missing_source_url_is_an_error(record: dict[str, Any]) -> None:
    del record["source"]
    with pytest.raises(ValueError, match="URL"):
        parse_urdb_record(record, "x")


def test_ratchet_is_flagged(record: dict[str, Any]) -> None:
    record["demandratchetpercentage"] = [0.0] * 11 + [0.8]
    assert parse_urdb_record(record, "x").ratchet_ignored


def test_tariff_without_any_demand_charge_is_rejected(record: dict[str, Any]) -> None:
    for key in ("demandratestructure", "flatdemandstructure"):
        del record[key]
    with pytest.raises(ValueError, match="no demand charge"):
        parse_urdb_record(record, "x")


def test_single_record_file_without_envelope(tmp_path: Path, record: dict[str, Any]) -> None:
    (tmp_path / "one.json").write_text(json.dumps(record))
    assert [t.tariff_id for t in load_tariff_dir(tmp_path)] == ["TEST-FIXTURE-TOU"]


def test_real_tariff_dir_loads() -> None:
    """Whatever tariff files are committed in data/tariffs/ must parse."""
    from ridgeline.config import load_settings

    settings = load_settings()
    for tariff in load_tariff_dir(settings.resolve(settings.paths.tariffs_dir)):
        assert not tariff.is_test_fixture


def test_assign_by_utility_and_size(record: dict[str, Any]) -> None:
    tariff = parse_urdb_record(record, "x")
    assert assign_tariff(_site(), [tariff]) == tariff
    assert assign_tariff(_site(peak_kw=1500.0), [tariff]) is None
    assert assign_tariff(_site(eiaid=11804), [tariff]) is None


def test_assign_refuses_ambiguous_match(record: dict[str, Any]) -> None:
    a = parse_urdb_record(record, "a")
    b = a.model_copy(update={"tariff_id": "other"})
    with pytest.raises(ValueError, match="several tariffs"):
        assign_tariff(_site(), [a, b])
