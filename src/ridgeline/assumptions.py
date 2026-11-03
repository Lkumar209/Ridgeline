"""Load and validate `assumptions.yaml`.

Every number that describes the world must carry either a source URL or the literal label
"ASSUMPTION". This module enforces that rule so an unsourced number fails `make check`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from ridgeline.config import REPO_ROOT

DEFAULT_ASSUMPTIONS = REPO_ROOT / "assumptions.yaml"


class Assumption(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float | int | str
    unit: str = Field(min_length=1)
    source: HttpUrl | Literal["ASSUMPTION"]
    notes: str = Field(min_length=1)
    low: float | None = Field(default=None, description="Lower end of the uncertainty range.")
    high: float | None = Field(default=None, description="Upper end of the uncertainty range.")

    @model_validator(mode="after")
    def _range(self) -> Assumption:
        if (self.low is None) != (self.high is None):
            raise ValueError("give both low and high, or neither")
        if self.low is not None and self.high is not None:
            if isinstance(self.value, str):
                raise ValueError("a range needs a numeric value")
            if not self.low <= float(self.value) <= self.high:
                raise ValueError("need low <= value <= high")
        return self

    @property
    def is_sourced(self) -> bool:
        return self.source != "ASSUMPTION"

    @property
    def number(self) -> float:
        if isinstance(self.value, str):
            raise ValueError("assumption is not numeric")
        return float(self.value)


def parse_assumptions(raw: dict[str, object]) -> dict[str, Assumption]:
    """Validate a mapping of name -> assumption fields."""
    return {name: Assumption.model_validate(fields) for name, fields in raw.items()}


def load_assumptions(path: Path = DEFAULT_ASSUMPTIONS) -> dict[str, Assumption]:
    with path.open() as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a mapping at the top level")
    return parse_assumptions(raw)
