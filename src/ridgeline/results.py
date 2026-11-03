"""Cache of simulated savings, keyed by a fingerprint of everything they depend on.

Simulating 40 site-years takes minutes; the Monte Carlo takes seconds. `ridgeline rank` reuses
savings only if the site list, tariff files, proxy rules, battery assumptions and the dispatch
code are byte-for-byte what produced them. Anything else triggers a re-simulation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from ridgeline.assumptions import load_assumptions
from ridgeline.config import REPO_ROOT, Settings

BATTERY_ASSUMPTIONS = (
    "battery_power_kw",
    "battery_energy_kwh",
    "battery_round_trip_efficiency",
    "battery_soc_min",
    "battery_soc_max",
    "power_factor_for_kva_demand",
)


def savings_fingerprint(settings: Settings, site_ids: list[str] | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(sorted(site_ids) if site_ids is not None else "all").encode())
    digest.update(settings.resolve(settings.paths.sites_file).read_bytes())
    for path in sorted(settings.resolve(settings.paths.tariffs_dir).glob("*.json")):
        digest.update(path.name.encode() + path.read_bytes())
    digest.update(json.dumps([p.model_dump() for p in settings.tariff_proxies]).encode())
    assumptions = load_assumptions()
    digest.update(json.dumps({k: assumptions[k].value for k in BATTERY_ASSUMPTIONS}).encode())
    for path in sorted((REPO_ROOT / "src" / "ridgeline" / "battery").glob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def cached_savings(
    settings: Settings,
    compute: Callable[[], pd.DataFrame],
    *,
    force: bool = False,
    site_ids: list[str] | None = None,
) -> tuple[pd.DataFrame, bool]:
    """Savings table from cache when the fingerprint matches, else `compute()` and store it.

    Returns (table, was_cached).
    """
    path = _cache_path(settings, savings_fingerprint(settings, site_ids))
    if path.exists() and not force:
        return pd.read_csv(path), True
    path.parent.mkdir(parents=True, exist_ok=True)
    compute().to_csv(path, index=False)
    # Return what a later cache hit would read, so hit and miss give byte-identical results
    # (pandas' CSV float parser can differ from the in-memory value in the last bit).
    return pd.read_csv(path), False


def _cache_path(settings: Settings, fingerprint: str) -> Path:
    return settings.resolve(settings.paths.cache_dir) / "results" / f"savings_{fingerprint}.csv"
