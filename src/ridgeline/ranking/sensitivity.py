"""Which inputs move the ranking, stated in numbers and in one plain sentence each.

Two kinds of sensitivity:
* tornado: move one uncertain input to its low and high value (others central, expected
  churn, no noise) and see how far NPVs swing and how many sites change rank;
* scenario comparisons: re-run the full Monte Carlo with one thing changed (proxy demand
  charge pinned at 0.7 / 1.3, churn switched off) and compare robustness rankings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ridgeline.scenarios.inputs import EconomicInputs, SiteEconomics
from ridgeline.scenarios.montecarlo import central_draws, expected_npv

MOVE_THRESHOLD = 3  # default "moves" = 3+ places; rank_sites raises it above seed noise
TOP_K = 10


@dataclass(frozen=True)
class RankShift:
    label: str
    spearman: float
    moved: int  # sites moving `threshold` or more places
    threshold: int
    max_move: int
    top_kept: int  # of the base top-K, how many stay in the top K
    n_sites: int
    sentence: str


def compare_ranks(
    base: pd.Series,
    other: pd.Series,
    label: str,
    what_changed: str,
    k: int = TOP_K,
    threshold: int = MOVE_THRESHOLD,
) -> RankShift:
    """Compare two rankings (Series of rank by site_id, 1 = best)."""
    other = other.reindex(base.index)
    moves = (other - base).abs()
    k = min(k, len(base))
    kept = int(((base <= k) & (other <= k)).sum())
    moved = int((moves >= threshold).sum())
    spearman = float(base.corr(other, method="spearman")) if len(base) > 1 else 1.0
    sentence = (
        f"{what_changed}: {verdict(moved, len(base))}. {moved} of {len(base)} sites "
        f"{moves_word(moved)} {threshold} or more places, and {kept} of the top {k} stay in the "
        f"top {k}."
    )
    return RankShift(label, spearman, moved, threshold, int(moves.max()), kept, len(base), sentence)


def moves_word(count: int) -> str:
    """'1 of 40 sites moves', '3 of 40 sites move'."""
    return "moves" if count == 1 else "move"


def verdict(moved: int, n_sites: int) -> str:
    """Words for how much an order changed, chosen from the count, never hard-coded."""
    if moved == 0:
        return "the order barely changes"
    if moved <= n_sites // 5:
        return "only a few sites change places"
    return "the order changes substantially"


def neighbour_gap(ranking: pd.DataFrame) -> float:
    """Median difference in robustness score between sites next to each other in the ranking."""
    scores = np.sort(ranking["robustness_score"].to_numpy())
    return float(np.median(np.diff(scores))) if len(scores) > 1 else 0.0


def ranks_by(values: np.ndarray, site_ids: list[str]) -> pd.Series:
    """Rank sites by a score, best (highest) first; ties broken by site_id."""
    frame = pd.DataFrame({"site_id": site_ids, "v": values})
    order = frame.sort_values(["v", "site_id"], ascending=[False, True])["site_id"]
    return pd.Series(np.arange(1, len(frame) + 1), index=order.to_numpy()).reindex(site_ids)


def tornado(
    sites: list[SiteEconomics], inputs: EconomicInputs, threshold: int = MOVE_THRESHOLD
) -> pd.DataFrame:
    """One row per uncertain input: NPV swing across its range and rank changes it causes."""
    ids = [s.site_id for s in sites]
    center = central_draws(inputs)
    base_npv = expected_npv(sites, inputs, center)[:, 0]
    base_rank = ranks_by(base_npv, ids)
    rows = []
    for name in EconomicInputs.UNCERTAIN:
        r = getattr(inputs, name)
        low = expected_npv(sites, inputs, center.with_value(name, r.low))[:, 0]
        high = expected_npv(sites, inputs, center.with_value(name, r.high))[:, 0]
        shifts = [
            compare_ranks(base_rank, ranks_by(v, ids), name, name, threshold=threshold)
            for v in (low, high)
        ]
        rows.append(
            {
                "input": name,
                "low": r.low,
                "central": r.central,
                "high": r.high,
                "median_npv_central": float(np.median(base_npv)),
                "median_npv_at_low": float(np.median(low)),
                "median_npv_at_high": float(np.median(high)),
                "npv_swing_usd": float(np.median(np.abs(high - low))),
                "sites_moved": max(s.moved for s in shifts),
                "max_move": max(s.max_move for s in shifts),
            }
        )
    return pd.DataFrame(rows).sort_values("npv_swing_usd", ascending=False).reset_index(drop=True)


def type_movers(base: pd.DataFrame, other: pd.DataFrame) -> pd.Series:
    """Mean rank change by building type (positive = moves down the list)."""
    merged = base.set_index("site_id")[["building_type", "rank"]].join(
        other.set_index("site_id")["rank"].rename("other")
    )
    return (merged["other"] - merged["rank"]).groupby(merged["building_type"]).mean().sort_values()


def churn_sentence(with_churn: pd.DataFrame, without: pd.DataFrame, shift: RankShift) -> str:
    """Plain-language effect of tenant churn on value and order."""
    change = (
        with_churn.set_index("site_id")["npv_p10"] - without.set_index("site_id")["npv_p10"]
    ).median()
    direction = "lowers" if change < 0 else "raises"
    movers = type_movers(without, with_churn)
    return (
        f"Allowing for the chance that a tenant leaves (and the battery stops earning) {direction} "
        f"a typical site's bad-case value (P10 NPV) by about ${abs(float(change)):,.0f}. "
        f"{movers.index[-1]} sites drop the most and {movers.index[0]} sites gain the most "
        f"places; {shift.moved} of {shift.n_sites} sites {moves_word(shift.moved)} "
        f"{shift.threshold} or more places."
    )
