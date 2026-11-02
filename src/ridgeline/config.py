"""Run configuration, loaded from `config/default.yaml`.

Configuration holds *how* to run (paths, seeds, selection rules). Facts about the world
(rates, costs, efficiencies) belong in `assumptions.yaml` instead, with a source for each one.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "default.yaml"
CONFIG_ENV_VAR = "RIDGELINE_CONFIG"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PathsConfig(_Frozen):
    cache_dir: Path
    tariffs_dir: Path
    sites_file: Path


class ComStockConfig(_Frozen):
    base_url: str
    upgrade: int = 0
    state: str = "MA"
    counties: list[str] = Field(min_length=1)


class ParTierQuota(_Frozen):
    low: int = Field(ge=0)
    mid: int = Field(ge=0)
    high: int = Field(ge=0)

    @property
    def total(self) -> int:
        return self.low + self.mid + self.high


class SiteSelectionConfig(_Frozen):
    seed: int
    n_per_type: int = Field(gt=0)
    building_types: list[str] = Field(min_length=1)
    peak_kw_min: float = Field(gt=0)
    peak_kw_max: float = Field(gt=0)
    par_tier_quota: ParTierQuota
    dev_subset_size: int = Field(gt=0)
    utility_eiaids: list[int] | None = Field(
        default=None, description="Keep only sites served by these utilities (EIA IDs)."
    )

    @model_validator(mode="after")
    def _consistent(self) -> SiteSelectionConfig:
        if self.peak_kw_min >= self.peak_kw_max:
            raise ValueError("peak_kw_min must be below peak_kw_max")
        if self.par_tier_quota.total != self.n_per_type:
            raise ValueError("par_tier_quota must sum to n_per_type")
        if self.dev_subset_size > self.n_sites:
            raise ValueError("dev_subset_size cannot exceed the number of sites")
        return self

    @property
    def n_sites(self) -> int:
        return self.n_per_type * len(self.building_types)


class Settings(_Frozen):
    paths: PathsConfig
    comstock: ComStockConfig
    site_selection: SiteSelectionConfig

    def resolve(self, path: Path) -> Path:
        """Interpret a configured path relative to the repository root."""
        return path if path.is_absolute() else REPO_ROOT / path


def load_settings(path: Path | None = None) -> Settings:
    """Load settings from `path`, `$RIDGELINE_CONFIG`, or the default config, in that order."""
    chosen = path or Path(os.environ.get(CONFIG_ENV_VAR, DEFAULT_CONFIG))
    with chosen.open() as f:
        raw = yaml.safe_load(f)
    return Settings.model_validate(raw)
