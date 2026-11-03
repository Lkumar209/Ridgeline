"""Golden ranking on a small fixed fixture: catches any unintended change in the M4 numbers.

Regenerate deliberately with: UPDATE_GOLDEN=1 uv run pytest tests/golden
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from ridgeline.ranking.pipeline import rank_sites
from tests.scenario_helpers import five_sites, inputs

GOLDEN = Path(__file__).parent / "ranking_five_sites.csv"
COLUMNS = ["site_id", "rank", "rank_by_p50", "npv_p10", "npv_p50", "npv_p90", "p_npv_positive"]


def test_ranking_matches_golden_file() -> None:
    table = rank_sites(five_sites(), inputs(), n_draws=1000, seed=2026).ranking[COLUMNS]
    if os.environ.get("UPDATE_GOLDEN"):
        table.to_csv(GOLDEN, index=False, float_format="%.2f")
    golden = pd.read_csv(GOLDEN)
    pd.testing.assert_frame_equal(
        table.reset_index(drop=True), golden, check_dtype=False, atol=0.01, rtol=0
    )
