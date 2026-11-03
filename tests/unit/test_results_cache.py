from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

from ridgeline.config import Settings, load_settings
from ridgeline.results import cached_savings, savings_fingerprint


def _settings_in(tmp: Path) -> Settings:
    settings = load_settings()
    sites = tmp / "sites.csv"
    shutil.copy(settings.resolve(settings.paths.sites_file), sites)
    paths = settings.paths.model_copy(update={"sites_file": sites, "cache_dir": tmp / "cache"})
    return settings.model_copy(update={"paths": paths})


def test_fingerprint_changes_when_inputs_change(tmp_path: Path) -> None:
    settings = _settings_in(tmp_path)
    before = savings_fingerprint(settings)
    sites = settings.paths.sites_file
    sites.write_text(sites.read_text().replace("MediumOffice", "MediumOffice ", 1))
    assert savings_fingerprint(settings) != before


def test_cache_hit_skips_recompute(tmp_path: Path) -> None:
    settings = _settings_in(tmp_path)
    calls = []

    def compute() -> pd.DataFrame:
        calls.append(1)
        return pd.DataFrame({"site_id": ["a"], "x": [1.0]})

    first, cached_first = cached_savings(settings, compute)
    second, cached_second = cached_savings(settings, compute)
    assert (cached_first, cached_second) == (False, True)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(first, second)
