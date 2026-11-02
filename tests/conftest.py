"""Shared fixtures. Everything here runs offline."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ridgeline.config import REPO_ROOT, SiteSelectionConfig, load_settings

FIXTURES = REPO_ROOT / "data" / "fixtures"
TEST_FIXTURES = REPO_ROOT / "tests" / "fixtures"
TYPES = ["MediumOffice", "Warehouse", "PrimarySchool"]


@pytest.fixture
def raw_sample() -> pd.DataFrame:
    """Real ComStock rows: 3 buildings, two weeks in Feb and two in Jul 2018."""
    return pd.read_parquet(FIXTURES / "comstock_raw_sample.parquet")


@pytest.fixture
def weather_sample_path() -> Path:
    return FIXTURES / "weather_G2500170_sample.csv"


@pytest.fixture
def tariff_fixture_path() -> Path:
    return TEST_FIXTURES / "tariff_test_fixture.json"


@pytest.fixture
def selection_cfg() -> SiteSelectionConfig:
    base = load_settings().site_selection
    return base.model_copy(
        update={
            "building_types": TYPES,
            "dev_subset_size": 4,
            "utility_eiaids": [11804, 54913],
        }
    )


def make_slim_metadata(n_per_type: int = 30, seed: int = 0) -> pd.DataFrame:
    """Synthetic slim metadata (already one row per building) for selection tests."""
    rng = np.random.default_rng(seed)
    rows = []
    bldg = 1
    for btype in TYPES:
        for _ in range(n_per_type):
            peak = float(rng.uniform(120, 900))
            par = float(rng.uniform(1.5, 8.0))
            rows.append(
                {
                    "bldg_id": bldg,
                    "weight": 1.0,
                    "building_type": btype,
                    "county_gisjoin": "G2500170",
                    "county_name": "MA, Middlesex County",
                    "tract_gisjoin": "G2500170000100",
                    "sqft": 20000.0,
                    "utility_eiaid": 11804 if bldg % 3 else 54913,
                    "peak_kw": peak,
                    "annual_kwh": peak / par * 8760,
                    "mean_kw": peak / par,
                }
            )
            bldg += 1
    frame = pd.DataFrame(rows)
    frame["utility_eiaid"] = frame["utility_eiaid"].astype("Int64")
    return frame
