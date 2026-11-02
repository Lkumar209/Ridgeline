"""Read and write the selected-site list (`data/sites.csv`, committed for reviewability)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ridgeline.data.schemas import Site

FIELDS = list(Site.model_fields)


def write_sites(sites: list[Site], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame([s.model_dump() for s in sites], columns=FIELDS)
    frame.to_csv(path, index=False, float_format="%.3f")


def read_sites(path: Path) -> list[Site]:
    frame = pd.read_csv(path, dtype={"utility_eiaid": "Int64"})
    records = frame.to_dict(orient="records")
    return [Site.model_validate(_clean(r)) for r in records]


def _clean(record: dict[object, object]) -> dict[str, object]:
    return {str(k): (None if pd.isna(v) else v) for k, v in record.items()}  # type: ignore[call-overload]
