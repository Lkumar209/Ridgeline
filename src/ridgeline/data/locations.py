"""Approximate map locations for sites.

ComStock gives no coordinates, only census geography from a weighted allocation (LIMITATIONS.md).
Each site is placed at the centroid of its PUMA (from ComStock's own PUMA boundary file), plus a
small deterministic offset so sites in the same PUMA do not sit on top of each other.
These are labeled "approximate" everywhere they appear.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from ridgeline.data.schemas import Site

JITTER_DEG = 0.01  # about 1 km: enough to separate pins, far smaller than a PUMA
PRECISION = "approximate: PUMA centroid + small offset"


def polygon_centroid(ring: list[list[float]]) -> tuple[float, float, float]:
    """Area-weighted centroid (lon, lat) and signed area of one closed ring (shoelace).

    Planar in degrees, which is fine at PUMA scale for placing a map pin.
    """
    pts = np.asarray(ring, dtype=float)
    x, y = pts[:, 0], pts[:, 1]
    cross = x[:-1] * y[1:] - x[1:] * y[:-1]
    area = cross.sum() / 2
    if area == 0:
        return float(x.mean()), float(y.mean()), 0.0
    cx = ((x[:-1] + x[1:]) * cross).sum() / (6 * area)
    cy = ((y[:-1] + y[1:]) * cross).sum() / (6 * area)
    return float(cx), float(cy), float(area)


def puma_centroids(geojson: dict[str, object]) -> dict[str, tuple[float, float]]:
    """GISJOIN -> (lat, lon), using each polygon's outer ring weighted by area."""
    features = geojson["features"]
    assert isinstance(features, list)
    out: dict[str, tuple[float, float]] = {}
    for feature in features:
        geometry = feature["geometry"]
        polygons = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        parts = [polygon_centroid(poly[0]) for poly in polygons]
        total = sum(abs(a) for _, _, a in parts)
        lon = sum(cx * abs(a) for cx, _, a in parts) / total
        lat = sum(cy * abs(a) for _, cy, a in parts) / total
        out[feature["properties"]["GISJOIN"]] = (lat, lon)
    return out


def jitter(bldg_id: int) -> tuple[float, float]:
    """Deterministic small offset (dlat, dlon) for a building."""
    rng = np.random.default_rng(bldg_id)
    angle, radius = rng.uniform(0, 2 * np.pi), JITTER_DEG * np.sqrt(rng.uniform())
    return float(radius * np.sin(angle)), float(radius * np.cos(angle))


def site_locations(
    sites: list[Site], puma_by_bldg: dict[int, str], centroids: dict[str, tuple[float, float]]
) -> pd.DataFrame:
    rows = []
    for site in sites:
        puma = puma_by_bldg[site.bldg_id]
        lat, lon = centroids[puma]
        dlat, dlon = jitter(site.bldg_id)
        rows.append(
            {
                "site_id": site.site_id,
                "puma_gisjoin": puma,
                "lat": round(lat + dlat, 5),
                "lon": round(lon + dlon, 5),
                "precision": PRECISION,
            }
        )
    return pd.DataFrame(rows)


def load_geojson(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text())
    assert isinstance(data, dict)
    return data


def read_locations(path: Path) -> pd.DataFrame:
    return pd.read_csv(path)
