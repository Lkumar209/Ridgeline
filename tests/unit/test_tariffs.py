from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from ridgeline.data.schemas import Site
from ridgeline.data.tariffs import (
    TariffMatchError,
    UnsupportedTariffError,
    load_tariff_dir,
    load_tariff_file,
    match_tariff,
    parse_urdb_record,
    tariff_coverage,
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


def test_unknown_demand_unit_is_refused(record: dict[str, Any]) -> None:
    record["demandunits"] = "hp"
    with pytest.raises(UnsupportedTariffError, match="hp"):
        parse_urdb_record(record, "x")


def test_kva_demand_without_power_factor_is_refused(record: dict[str, Any]) -> None:
    record["demandunits"] = record["flatdemandunit"] = "kVA"
    with pytest.raises(UnsupportedTariffError, match="no power factor"):
        parse_urdb_record(record, "x")


def test_kva_demand_converts_to_kw_with_power_factor(record: dict[str, Any]) -> None:
    """$/kVA x (kW / PF) = ($/kVA / PF) x kW, for both TOU and flat demand charges."""
    record["demandunits"] = record["flatdemandunit"] = "kVA"
    tariff = parse_urdb_record(record, "x", power_factor=0.8)
    assert tariff.demand_converted_from_kva_at_pf == 0.8
    assert tariff.demand_tou_usd_per_kw is not None
    assert tariff.demand_tou_usd_per_kw.rate_at(7, 15, False) == pytest.approx(5.0 / 0.8)
    assert tariff.flat_demand_usd_per_kw_by_month is not None
    assert tariff.flat_demand_usd_per_kw_by_month[0] == pytest.approx(10.0 / 0.8)
    # Energy rates are untouched by the conversion.
    assert tariff.energy_usd_per_kwh.rate_at(1, 12, False) == 0.20


def test_kw_tariff_ignores_power_factor(record: dict[str, Any]) -> None:
    tariff = parse_urdb_record(record, "x", power_factor=0.8)
    assert tariff.demand_converted_from_kva_at_pf is None
    assert tariff.flat_demand_usd_per_kw_by_month is not None
    assert tariff.flat_demand_usd_per_kw_by_month[0] == 10.0


def test_mixed_kw_and_kva_is_refused(record: dict[str, Any]) -> None:
    record["flatdemandunit"] = "kVA"
    with pytest.raises(UnsupportedTariffError, match="mixed"):
        parse_urdb_record(record, "x", power_factor=0.9)


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


def test_match_by_utility_and_size(record: dict[str, Any]) -> None:
    tariff = parse_urdb_record(record, "x")
    assert match_tariff(_site(), [tariff]) == tariff


@pytest.mark.parametrize(("peak", "eiaid"), [(1500.0, 99999), (300.0, 11804)])
def test_match_fails_loudly_when_nothing_matches(
    record: dict[str, Any], peak: float, eiaid: int
) -> None:
    tariff = parse_urdb_record(record, "x")
    with pytest.raises(TariffMatchError, match="matches no tariff"):
        match_tariff(_site(peak_kw=peak, eiaid=eiaid), [tariff])


def test_match_fails_loudly_on_two_matches(record: dict[str, Any]) -> None:
    a = parse_urdb_record(record, "a")
    b = a.model_copy(update={"tariff_id": "other"})
    with pytest.raises(TariffMatchError, match="several tariffs"):
        match_tariff(_site(), [a, b])


def test_coverage_report(record: dict[str, Any]) -> None:
    tariff = parse_urdb_record(record, "x")
    sites = [_site(), _site(peak_kw=1500.0).model_copy(update={"site_id": "cs-2"})]
    coverage = tariff_coverage(sites, [tariff])
    assert coverage.matched == {"cs-1": "TEST-FIXTURE-TOU"}
    assert coverage.unmatched == ["cs-2"]
    assert not coverage.complete


def test_usage_limits_are_parsed_and_enforced(record: dict[str, Any]) -> None:
    record["peakkwhusagemin"] = 10_000
    tariff = parse_urdb_record(record, "x")
    assert tariff.min_monthly_kwh == 10_000
    small = _site().model_copy(update={"mean_kw": 10.0})  # 7,300 kWh/month
    assert small.mean_monthly_kwh == pytest.approx(7_300)
    with pytest.raises(TariffMatchError, match="7,300 kWh/month"):
        match_tariff(small, [tariff])
    assert match_tariff(_site(), [tariff]) == tariff  # 100 kW mean = 73,000 kWh/month


def test_peak_limit_is_inclusive(record: dict[str, Any]) -> None:
    record["peakkwcapacitymax"] = 200
    tariff = parse_urdb_record(record, "x")
    assert match_tariff(_site(peak_kw=200.0), [tariff]) == tariff
    with pytest.raises(TariffMatchError):
        match_tariff(_site(peak_kw=200.01), [tariff])


def test_multi_url_source_is_split_not_glued(record: dict[str, Any]) -> None:
    """Regression: URDB `source` can hold several URLs separated by blank lines."""
    record["source"] = "https://a.example/one.pdf\r\n\r\nhttps://b.example/two.pdf"
    urls = [str(u) for u in parse_urdb_record(record, "x").source_urls]
    assert urls == ["https://a.example/one.pdf", "https://b.example/two.pdf"]


def test_committed_meco_g2_matches_its_published_values() -> None:
    """Data contract for data/tariffs/meco_g2_sema.json (URDB 67d08dea7568c8189f03c54e)."""
    from ridgeline.config import REPO_ROOT

    (g2,) = load_tariff_file(REPO_ROOT / "data" / "tariffs" / "meco_g2_sema.json")
    assert (g2.eiaid, g2.tariff_id) == (11804, "67d08dea7568c8189f03c54e")
    assert g2.flat_demand_usd_per_kw_by_month == [14.82] * 12
    assert g2.demand_tou_usd_per_kw is None
    assert g2.energy_usd_per_kwh.rates == [0.0733]
    assert g2.fixed_monthly_usd == 45.0
    assert (g2.min_peak_kw, g2.max_peak_kw) == (None, 200.0)
    assert (g2.min_monthly_kwh, g2.max_monthly_kwh) == (10_000.0, None)
    assert str(g2.effective_date) == "2025-02-01"
    assert [str(u).rsplit("/", 1)[-1] for u in g2.source_urls] == [
        "meco_delivery.pdf",
        "meco_basic_service.pdf",
        "meco_g2.pdf",
    ]
    assert not g2.is_test_fixture and not g2.ratchet_ignored


# --- proxies (ADR-010) ------------------------------------------------------------------


def _capped(record: dict[str, Any]) -> Any:
    record.update(eiaid=11804, peakkwcapacitymax=200)
    return parse_urdb_record(record, "base")


def _rule(**overrides: Any) -> Any:
    from ridgeline.config import TariffProxy

    fields = {
        "base_tariff_id": "TEST-FIXTURE-TOU",
        "eiaid": 11804,
        "applies_above_kw": 200,
        "assumption_key": "g2_proxy_above_200kw",
    }
    return TariffProxy(**{**fields, **overrides})


def test_proxy_covers_sites_above_the_cap_only(record: dict[str, Any]) -> None:
    from ridgeline.data.tariffs import with_proxies

    tariffs = with_proxies([_capped(record)], [_rule()])
    big = match_tariff(_site(peak_kw=650.0, eiaid=11804), tariffs)
    assert big.is_proxy and big.proxy_of == "TEST-FIXTURE-TOU"
    assert big.tariff_id == "TEST-FIXTURE-TOU+proxy>200kW"
    assert big.flat_demand_usd_per_kw_by_month == tariffs[0].flat_demand_usd_per_kw_by_month
    # Exactly at the cap: the real tariff only, never ambiguous.
    assert not match_tariff(_site(peak_kw=200.0, eiaid=11804), tariffs).is_proxy


def test_proxy_keeps_the_usage_minimum(record: dict[str, Any]) -> None:
    from ridgeline.data.tariffs import with_proxies

    record["peakkwhusagemin"] = 10_000
    tariffs = with_proxies([_capped(record)], [_rule()])
    tiny_use = _site(peak_kw=650.0, eiaid=11804).model_copy(update={"mean_kw": 5.0})
    with pytest.raises(TariffMatchError, match="matches no tariff"):
        match_tariff(tiny_use, tariffs)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [({"base_tariff_id": "nope"}, "unknown tariff"), ({"applies_above_kw": 150}, "kW cap")],
)
def test_proxy_rule_must_match_its_base(
    record: dict[str, Any], overrides: dict[str, Any], message: str
) -> None:
    from ridgeline.data.tariffs import with_proxies

    with pytest.raises(ValueError, match=message):
        with_proxies([_capped(record)], [_rule(**overrides)])


def test_configured_proxies_name_an_assumption_labeled_as_such() -> None:
    """Every proxy in config must be backed by an ASSUMPTION entry in assumptions.yaml."""
    from ridgeline.assumptions import load_assumptions
    from ridgeline.config import load_settings

    assumptions = load_assumptions()
    for rule in load_settings().tariff_proxies:
        assert assumptions[rule.assumption_key].source == "ASSUMPTION"


def test_committed_meco_g3_matches_its_published_values() -> None:
    """Data contract for data/tariffs/meco_g3_sema.json (URDB 67d0b140ad6db765a70b0a5c).

    Values are the 2025-02-01 URDB snapshot; National Grid's later rates differ (ADR-016).
    """
    from ridgeline.battery.billing import demand_billed, interval_prices
    from ridgeline.config import REPO_ROOT

    (g3,) = load_tariff_file(REPO_ROOT / "data" / "tariffs" / "meco_g3_sema.json")
    assert (g3.eiaid, g3.tariff_id) == (11804, "67d0b140ad6db765a70b0a5c")
    assert g3.name == "G-3 Time of Use SEMA Load Zone"
    assert g3.flat_demand_usd_per_kw_by_month == [0.0] * 12
    assert g3.demand_tou_usd_per_kw is not None
    assert g3.demand_tou_usd_per_kw.rates == [0.0, 8.55]
    assert g3.energy_usd_per_kwh.rates == [0.00815, 0.01074]
    assert g3.fixed_monthly_usd == 350.0
    assert (g3.min_peak_kw, g3.max_peak_kw) == (200.0, None)
    assert str(g3.effective_date) == "2025-02-01"
    assert [str(u).rsplit("/", 1)[-1] for u in g3.source_urls] == [
        "meco_delivery.pdf",
        "meco_basic_service.pdf",
        "meco_g3.pdf",
    ]
    # Demand is billed on weekdays 8:00-20:59 local only (the tariff's 8 a.m.-9 p.m. peak).
    index = pd.date_range("2018-07-09 04:00", periods=7 * 96, freq="15min", tz="UTC")  # Mon
    billed = demand_billed(interval_prices(index, g3))
    local = index.tz_convert("America/New_York")
    expected = (local.day_of_week < 5) & (local.hour >= 8) & (local.hour < 21)
    np.testing.assert_array_equal(billed, np.asarray(expected))


def test_committed_g2_and_g3_split_sites_at_200_kw() -> None:
    from ridgeline.config import REPO_ROOT

    tariffs = load_tariff_dir(REPO_ROOT / "data" / "tariffs")
    by_name = {t.name: t for t in tariffs}
    g2, g3 = by_name["G-2 Demand SEMA Load Zone"], by_name["G-3 Time of Use SEMA Load Zone"]
    assert g2.is_eligible(150.0, 20_000.0) and not g3.is_eligible(150.0, 20_000.0)
    assert g3.is_eligible(450.0, 90_000.0) and not g2.is_eligible(450.0, 90_000.0)
