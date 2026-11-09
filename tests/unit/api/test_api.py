"""API tests on in-memory data: no network, no cache, no `ridgeline rank` run needed."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ridgeline.api.app import create_app
from ridgeline.api.data import ApiData, MissingResultsError, daily_load
from ridgeline.data.schemas import Site
from ridgeline.ranking.pipeline import rank_sites
from tests.gaps_helpers import weekly_profile_series, year_index
from tests.scenario_helpers import five_sites, inputs


def _site(economics_site_id: str, bldg_id: int, btype: str) -> Site:
    return Site(
        site_id=economics_site_id,
        bldg_id=bldg_id,
        building_type=btype,
        county_gisjoin="G2500170",
        county_name="MA, Middlesex County",
        tract_gisjoin="T",
        utility_eiaid=11804,
        sqft=10000.0,
        peak_kw=180.0,
        mean_kw=60.0,
        par_tier="mid",
        dev_subset=False,
    )


@pytest.fixture(scope="module")
def api_data() -> ApiData:
    tariff_ids = ["T-G2", "T-G2", "T-G3", "T-G3", "T-G2"]
    economics = [
        e.model_copy(update={"tariff_id": t}) for e, t in zip(five_sites(), tariff_ids, strict=True)
    ]
    result = rank_sites(economics, inputs(), n_draws=300, seed=1)
    sites = {e.site_id: _site(e.site_id, e.bldg_id, e.building_type) for e in economics}
    locations = pd.DataFrame(
        {
            "site_id": list(sites),
            "lat": [42.3 + i / 100 for i in range(5)],
            "lon": [-71.1] * 5,
            "precision": "approximate: test",
        }
    ).set_index("site_id")
    load = weekly_profile_series(year_index())
    return ApiData(
        sites=sites,
        locations=locations,
        ranking=result.ranking.set_index("site_id"),
        fan=result.fan,
        revenue_sweep=result.revenue_sweep,
        explanations=result.explanations,
        run={"n_draws": 300, "seed": 1, "seconds": 0.1},
        daily_load=lambda site: daily_load(load),
        tariff_names={"T-G2": "G-2 Demand (test)", "T-G3": "G-3 Time of Use (test)"},
    )


@pytest.fixture(scope="module")
def client(api_data: ApiData) -> TestClient:
    return TestClient(create_app(lambda: api_data))


def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_sites_are_listed_in_rank_order_with_locations(client: TestClient) -> None:
    body = client.get("/api/sites").json()
    assert [s["rank"] for s in body] == [1, 2, 3, 4, 5]
    assert all(s["location"]["precision"].startswith("approximate") for s in body)
    assert {"breakeven_capex_usd_per_kw", "tariff_is_proxy"} <= set(body[0])


def test_rankings_carry_explanations_and_revenue_sweep(client: TestClient) -> None:
    body = client.get("/api/rankings").json()
    assert body["illustrative"] is True
    assert "headline" in body["explanations"] and "other_revenue" in body["explanations"]
    rows = body["rows"]
    assert [r["rank"] for r in rows] == sorted(r["rank"] for r in rows)
    assert all(r["npv_p10"] <= r["npv_p50"] <= r["npv_p90"] for r in rows)
    assert body["revenue_sweep"][0]["other_revenue_usd_per_kw_year"] == 0


def test_site_detail_has_load_curve_and_fan(client: TestClient) -> None:
    body = client.get("/api/sites/s3").json()
    assert body["site"]["site_id"] == "s3"
    assert len(body["load_curve"]) == 365
    fan = body["fan"]
    assert [p["year"] for p in fan] == list(range(16))
    assert all(p["p10"] <= p["p50"] <= p["p90"] for p in fan)
    assert fan[-1]["p50"] == pytest.approx(body["ranking"]["npv_p50"])


def test_unknown_site_is_404(client: TestClient) -> None:
    response = client.get("/api/sites/nope")
    assert response.status_code == 404
    assert "unknown site" in response.json()["detail"]


def test_missing_results_is_503_with_a_hint() -> None:
    def no_results() -> ApiData:
        raise MissingResultsError("missing ranking.csv; run `ridgeline rank` first")

    response = TestClient(create_app(no_results)).get("/api/sites")
    assert response.status_code == 503
    assert "ridgeline rank" in response.json()["detail"]


def test_map_page_is_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "illustrative" in response.text and "app.js" in response.text
    for asset in ("/app.js", "/styles.css"):
        assert client.get(asset).status_code == 200


def test_daily_load_uses_local_days() -> None:
    frame = daily_load(weekly_profile_series(year_index()))
    assert len(frame) == 365 and frame["date"].iloc[0] == "2018-01-01"
    assert (frame["peak_kw"] >= frame["mean_kw"]).all()


def test_breakeven_label_is_served_and_matches_the_number(client: TestClient) -> None:
    """Regression: the page showed '-$27/kW'; it must say it never pays back instead."""
    rows = client.get("/api/rankings").json()["rows"]
    sites = client.get("/api/sites").json()
    for item in [*rows, *sites]:
        value, label = item["breakeven_capex_usd_per_kw"], item["breakeven_label"]
        if value <= 0:
            assert label == "never pays back, even at $0 battery cost"
        else:
            assert label.endswith("/kW") and not label.startswith("-")
    detail = client.get(f"/api/sites/{sites[0]['site_id']}").json()
    assert detail["ranking"]["breakeven_label"] == detail["site"]["breakeven_label"]


def test_sites_name_their_tariff(client: TestClient, api_data: ApiData) -> None:
    """Regression: the page labelled every non-proxy site 'MECo G-2', including G-3 sites."""
    by_id = {s["site_id"]: s for s in client.get("/api/sites").json()}
    for site_id, row in api_data.ranking.iterrows():
        expected = api_data.tariff_names[row["tariff_id"]]
        if row["tariff_is_proxy"]:
            expected += " (values used as a proxy)"
        assert by_id[site_id]["tariff"] == expected
    assert any("G-3" in s["tariff"] for s in by_id.values())
    assert any("proxy" in s["tariff"] for s in by_id.values())
