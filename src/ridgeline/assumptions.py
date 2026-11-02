"""Load and validate `assumptions.yaml`.

Every number that describes the world must carry either a source URL or the literal label
"ASSUMPTION". This module enforces that rule so an unsourced number fails `make check`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ridgeline.config import REPO_ROOT

DEFAULT_ASSUMPTIONS = REPO_ROOT / "assumptions.yaml"


class Assumption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float | int | str
    unit: str = Field(min_length=1)
    source: HttpUrl | Literal["ASSUMPTION"]
    notes: str = Field(min_length=1)

    @property
    def is_sourced(self) -> bool:
        return self.source != "ASSUMPTION"


def parse_assumptions(raw: dict[str, object]) -> dict[str, Assumption]:
    """Validate a mapping of name -> assumption fields."""
    return {name: Assumption.model_validate(fields) for name, fields in raw.items()}


def load_assumptions(path: Path = DEFAULT_ASSUMPTIONS) -> dict[str, Assumption]:
    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return parse_assumptions(raw)
