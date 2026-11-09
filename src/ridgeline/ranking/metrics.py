"""Turn NPV draws into the ranking table.

Robustness score = P10 NPV: "in 9 out of 10 simulated futures, this site does at least this well".
Ranking by it favors sites that hold up in bad cases over sites that only look good on average.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ridgeline.scenarios.inputs import SiteEconomics


def summarize_npv(npv: np.ndarray, sites: list[SiteEconomics]) -> pd.DataFrame:
    """One row per site: NPV percentiles, P(NPV>0), robustness score and ranks (1 = best)."""
    if npv.shape[0] != len(sites):
        raise ValueError("one NPV row per site expected")
    p10, p50, p90 = np.percentile(npv, [10, 50, 90], axis=1)
    frame = pd.DataFrame(
        {
            "site_id": [s.site_id for s in sites],
            "building_type": [s.building_type for s in sites],
            "tariff_is_proxy": [s.tariff_is_proxy for s in sites],
            "tariff_id": [s.tariff_id for s in sites],
            "npv_p10": p10,
            "npv_p50": p50,
            "npv_p90": p90,
            "npv_mean": npv.mean(axis=1),
            "p_npv_positive": (npv > 0).mean(axis=1),
            "robustness_score": p10,
        }
    )
    frame["rank"] = _rank(frame, ["robustness_score", "npv_p50"])
    frame["rank_by_p50"] = _rank(frame, ["npv_p50", "robustness_score"])
    return frame.sort_values("rank").reset_index(drop=True)


def _rank(frame: pd.DataFrame, by: list[str]) -> pd.Series:
    """Dense 1..S ranking, best first, ties broken by the next key and then site_id."""
    order = frame.sort_values([*by, "site_id"], ascending=[False] * len(by) + [True]).index
    ranks = pd.Series(0, index=frame.index, dtype=int)
    ranks[order] = np.arange(1, len(frame) + 1)
    return ranks
