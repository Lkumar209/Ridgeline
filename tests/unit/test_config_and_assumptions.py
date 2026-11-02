from __future__ import annotations

import pytest
from pydantic import ValidationError

from ridgeline.assumptions import load_assumptions, parse_assumptions
from ridgeline.config import load_settings


def test_default_config_loads() -> None:
    settings = load_settings()
    assert settings.site_selection.n_sites == 40
    assert settings.site_selection.dev_subset_size == 10


def test_quota_must_sum_to_types_per_site() -> None:
    sel = load_settings().site_selection.model_dump()
    sel["par_tier_quota"]["low"] += 1
    with pytest.raises(ValidationError, match="sum to n_per_type"):
        type(load_settings().site_selection).model_validate(sel)


def test_every_assumption_is_sourced_or_labeled() -> None:
    """Principle 2: no number without a source URL or the ASSUMPTION label."""
    assumptions = load_assumptions()
    assert assumptions
    for name, a in assumptions.items():
        assert a.is_sourced or a.source == "ASSUMPTION", name


@pytest.mark.parametrize(
    "fields",
    [
        {"value": 1, "unit": "kW", "notes": "n"},  # no source at all
        {"value": 1, "unit": "kW", "notes": "n", "source": "my head"},  # not a URL
        {"value": 1, "unit": "kW", "source": "ASSUMPTION"},  # no notes
    ],
)
def test_unsourced_assumptions_are_rejected(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        parse_assumptions({"x": fields})


def test_ranges_must_bracket_the_value() -> None:
    base = {"unit": "x", "source": "ASSUMPTION", "notes": "n"}
    parse_assumptions({"ok": {**base, "value": 1.0, "low": 0.5, "high": 2.0}})
    with pytest.raises(ValidationError, match="low <= value <= high"):
        parse_assumptions({"x": {**base, "value": 3.0, "low": 0.5, "high": 2.0}})
    with pytest.raises(ValidationError, match="both low and high"):
        parse_assumptions({"x": {**base, "value": 1.0, "low": 0.5}})
