from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ridgeline.config import SiteSelectionConfig
from ridgeline.data.comstock import select_sites
from ridgeline.data.sites import read_sites, write_sites
from ridgeline.data.weather import load_weather
from tests.conftest import make_slim_metadata


def test_weather_is_utc_hour_start(weather_sample_path: Path) -> None:
    weather = load_weather(weather_sample_path)
    assert str(pd.DatetimeIndex(weather.index).tz) == "UTC"
    assert list(weather.columns) == ["temp_c", "rh_pct", "wind_ms", "ghi_wm2"]
    # First row is stamped 01:00 EST (hour-ending) -> hour starting 00:00 EST = 05:00 UTC.
    assert weather.index[0] == pd.Timestamp("2018-02-05 05:00", tz="UTC")


def test_weather_solar_noon_is_near_local_noon(weather_sample_path: Path) -> None:
    """Sanity check of the same timestamp convention on weather: GHI peaks around midday."""
    weather = load_weather(weather_sample_path)
    local = weather.tz_convert("America/New_York")
    index = pd.DatetimeIndex(local.index)
    for month in (2, 7):
        ghi = local.loc[index.month == month, "ghi_wm2"]
        hours = pd.DatetimeIndex(ghi.index).hour
        means = [ghi[hours == h].mean() for h in range(24)]
        peak_hour = int(np.nanargmax(means))
        assert 11 <= peak_hour <= 13


def test_sites_csv_round_trip(tmp_path: Path, selection_cfg: SiteSelectionConfig) -> None:
    sites = select_sites(make_slim_metadata(), selection_cfg)
    path = tmp_path / "sites.csv"
    write_sites(sites, path)
    loaded = read_sites(path)
    assert [s.site_id for s in loaded] == [s.site_id for s in sites]
    assert loaded[0].peak_kw == round(sites[0].peak_kw, 3)


def test_committed_sites_file_is_valid() -> None:
    sites = read_sites(Path(__file__).resolve().parents[2] / "data" / "sites.csv")
    assert len(sites) == 40
    assert sum(s.dev_subset for s in sites) == 10
    assert all(100 <= s.peak_kw <= 1000 for s in sites)
