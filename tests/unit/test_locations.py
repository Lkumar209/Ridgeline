from __future__ import annotations

from pathlib import Path

import pytest

from ridgeline.config import REPO_ROOT
from ridgeline.data.locations import (
    JITTER_DEG,
    jitter,
    polygon_centroid,
    puma_centroids,
    read_locations,
)
from ridgeline.data.sites import read_sites


def test_centroid_of_unit_square() -> None:
    cx, cy, area = polygon_centroid([[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]])
    assert (cx, cy, abs(area)) == pytest.approx((0.5, 0.5, 1.0))


def test_multipolygon_centroid_is_area_weighted() -> None:
    big = [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]  # area 4, centroid (1, 1)
    small = [[[10, 0], [11, 0], [11, 1], [10, 1], [10, 0]]]  # area 1, centroid (10.5, 0.5)
    geo: dict[str, object] = {
        "features": [
            {
                "properties": {"GISJOIN": "P1"},
                "geometry": {"type": "MultiPolygon", "coordinates": [big, small]},
            }
        ]
    }
    lat, lon = puma_centroids(geo)["P1"]
    assert lon == pytest.approx((1 * 4 + 10.5 * 1) / 5)
    assert lat == pytest.approx((1 * 4 + 0.5 * 1) / 5)


def test_jitter_is_deterministic_and_small() -> None:
    assert jitter(123) == jitter(123)
    dlat, dlon = jitter(456)
    assert (dlat**2 + dlon**2) ** 0.5 <= JITTER_DEG


def test_committed_locations_cover_every_site_inside_massachusetts() -> None:
    sites = read_sites(REPO_ROOT / "data" / "sites.csv")
    locations = read_locations(Path(REPO_ROOT / "data" / "site_locations.csv"))
    assert set(locations["site_id"]) == {s.site_id for s in sites}
    assert locations["lat"].between(41.2, 42.9).all()
    assert locations["lon"].between(-73.5, -69.9).all()
    assert locations["precision"].str.startswith("approximate").all()
