"""`ridgeline simulate` must refuse to run when any site lacks a unique tariff."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import typer

from ridgeline.cli import _tariffs_for
from ridgeline.config import Settings, load_settings
from ridgeline.data.sites import read_sites
from tests.battery_helpers import FIXTURE


def _settings_with_tariff_dir(directory: Path) -> Settings:
    settings = load_settings()
    paths = settings.paths.model_copy(update={"tariffs_dir": directory})
    return settings.model_copy(update={"paths": paths})


def test_simulate_exits_listing_unmatched_sites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings_with_tariff_dir(tmp_path)  # empty: no tariffs at all
    sites = [s for s in read_sites(settings.resolve(settings.paths.sites_file)) if s.dev_subset]
    with pytest.raises(typer.Exit) as exc:
        _tariffs_for(settings, sites, None)
    assert exc.value.exit_code == 1
    err = capsys.readouterr().err
    assert "10 of 10 sites have no unique tariff" in err
    assert all(s.site_id in err for s in sites)


def test_override_applies_one_tariff_to_every_site(tmp_path: Path) -> None:
    settings = _settings_with_tariff_dir(tmp_path)
    sites = read_sites(settings.resolve(settings.paths.sites_file))[:3]
    copy = tmp_path / "fixture.json"
    shutil.copy(FIXTURE, copy)
    matched = _tariffs_for(settings, sites, copy)
    assert {t.tariff_id for t in matched.values()} == {"TEST-FIXTURE-TOU"}
    assert all(t.is_test_fixture for t in matched.values())
