"""Rebuild the small, committed test fixtures in data/fixtures/ from real ComStock files.

Usage: uv run python scripts/build_fixtures.py

Fixtures are raw ComStock rows (naive local-standard, interval-ending stamps) for two
weeks in February (EST) and two in July (EDT), so tests exercise the real timestamp
convention offline. Files stay well under 1 MB in total.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pandas as pd

from ridgeline.config import REPO_ROOT, load_settings
from ridgeline.data.cache import download
from ridgeline.data.comstock import (
    LIGHTING_KWH_COL,
    TOTAL_KWH_COL,
    timeseries_url,
    weather_url,
)

FIXTURE_DIR = REPO_ROOT / "data" / "fixtures"
# Dev-subset sites with strong daily schedules: an office, a school, a warehouse.
BLDG_IDS = (68361, 45533, 31197)
WEATHER_COUNTY = "G2500170"
WINDOWS = (("2018-02-05 00:15", "2018-02-19 00:00"), ("2018-07-09 00:15", "2018-07-23 00:00"))


def _slice(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    stamps = pd.to_datetime(frame[column])
    parts = [frame[(stamps >= lo) & (stamps <= hi)] for lo, hi in WINDOWS]
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    cfg = load_settings().comstock
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    frames = []
    with httpx.Client() as client, tempfile.TemporaryDirectory() as tmp:
        for bldg_id in BLDG_IDS:
            path = download(timeseries_url(cfg, bldg_id), Path(tmp) / f"{bldg_id}.parquet", client)
            raw = pd.read_parquet(path, columns=["timestamp", TOTAL_KWH_COL, LIGHTING_KWH_COL])
            raw = raw.reset_index()
            frames.append(_slice(raw, "timestamp"))
        weather_path = download(weather_url(cfg, WEATHER_COUNTY), Path(tmp) / "w.csv", client)
        weather = _slice(pd.read_csv(weather_path), "date_time")
    pd.concat(frames, ignore_index=True).to_parquet(FIXTURE_DIR / "comstock_raw_sample.parquet")
    weather.to_csv(FIXTURE_DIR / f"weather_{WEATHER_COUNTY}_sample.csv", index=False)


if __name__ == "__main__":
    main()
