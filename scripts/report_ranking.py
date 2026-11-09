"""Write docs/m4/ from the latest `ridgeline rank` outputs, so documented numbers match the code.

Usage: uv run ridgeline rank && uv run python scripts/report_ranking.py
"""

from __future__ import annotations

import json
import shutil

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch

from ridgeline.config import REPO_ROOT, load_settings
from ridgeline.ranking.pipeline import breakeven_label

OUT = REPO_ROOT / "docs" / "m4"
# Reference palette slots 1-2 (validated for color vision deficiency); labels carry identity too.
SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
LOW, HIGH = "#2a78d6", "#eb6834"
NAMES = {
    "capex_usd_per_kw": "Battery cost ($/kW)",
    "incentive": "Upfront incentive",
    "om_usd_per_kw_year": "O&M cost",
    "churn_multiplier": "Tenant churn risk",
    "proxy_demand_multiplier": "Proxy demand charge (23 sites)",
    "discount_rate": "Discount rate",
    "escalation": "Tariff escalation",
    "capacity_fade": "Capacity fade",
}


def _money(v: float) -> str:
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}"


def plot_tornado(tornado: pd.DataFrame, threshold: int) -> None:
    t = tornado.iloc[::-1].reset_index(drop=True)
    center = float(t["median_npv_central"].iloc[0])
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    for i, row in t.iterrows():
        for value, color in ((row["median_npv_at_low"], LOW), (row["median_npv_at_high"], HIGH)):
            ax.barh(i, value - center, left=center, height=0.6, color=color, edgecolor=SURFACE)
        moved = int(row["sites_moved"])
        ax.annotate(
            f"{moved} site{'s' if moved != 1 else ''} move {threshold}+ places",
            xy=(max(row["median_npv_at_low"], row["median_npv_at_high"]), i),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
            color=INK_2,
        )
    ax.axvline(center, color=MUTED, linewidth=1)
    ax.set_yticks(range(len(t)), [NAMES.get(n, n) for n in t["input"]], color=INK_2, fontsize=9)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: _money(v)))
    ax.tick_params(colors=INK_2, labelsize=9)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel("Median site NPV (central case, expected churn)", color=INK_2, fontsize=9)
    ax.set_title("What moves value, and what moves the order", color=INK, fontsize=11, loc="left")
    # NPV = 0 (break-even) on purpose: it shows how far every input range is from viability.
    ax.axvline(0, color=INK, linewidth=1)
    ax.annotate(
        "NPV = 0",
        xy=(0, len(t) - 0.5),
        xytext=(-4, 0),
        textcoords="offset points",
        ha="right",
        va="center",
        fontsize=8,
        color=INK_2,
    )
    handles = [
        Patch(color=LOW, label="input at low end"),
        Patch(color=HIGH, label="input at high end"),
    ]
    ax.legend(
        handles=handles,
        frameon=False,
        fontsize=8,
        labelcolor=INK_2,
        loc="lower right",
        bbox_to_anchor=(0.88, 0.0),
    )
    fig.text(0.01, 0.01, "Illustrative. Ranges in assumptions.yaml.", color=MUTED, fontsize=8)
    fig.tight_layout(rect=(0, 0.03, 0.97, 1))
    fig.savefig(OUT / "tornado.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _table(headers: list[str], rows: list[list[object]]) -> list[str]:
    return [
        "| " + " | ".join(headers) + " |",
        "|" + "---|" * len(headers),
        *["| " + " | ".join(str(c) for c in row) + " |" for row in rows],
    ]


def write_results(
    ranking: pd.DataFrame, tornado: pd.DataFrame, shifts: pd.DataFrame, info: dict[str, object]
) -> None:
    run, text = info["run"], info["explanations"]
    assert isinstance(run, dict) and isinstance(text, dict)
    # Threshold used for the scenario and tornado comparisons (above seed-to-seed noise).
    threshold = int(shifts.loc[shifts["label"] == "churn_on_vs_off", "threshold"].iloc[0])
    top = _table(
        [
            "Rank",
            "Site",
            "Type",
            "Proxy tariff",
            "P10 NPV",
            "P50 NPV",
            "P90 NPV",
            "Rank by P50",
            "Breakeven battery cost",
            "Other revenue needed $/kW-yr",
        ],
        [
            [
                r["rank"],
                r["site_id"],
                r["building_type"],
                "yes" if r["tariff_is_proxy"] else "no",
                _money(r["npv_p10"]),
                _money(r["npv_p50"]),
                _money(r["npv_p90"]),
                r["rank_by_p50"],
                breakeven_label(float(r["breakeven_capex_usd_per_kw"])),
                _money(r["required_other_revenue_usd_per_kw_year"]),
            ]
            for _, r in ranking.head(10).iterrows()
        ],
    )
    swings = _table(
        [
            "Input",
            "Low",
            "High",
            "Median NPV at low",
            "Median NPV at high",
            "Median swing",
            f"Sites moving {threshold}+ places",
        ],
        [
            [
                NAMES.get(r["input"], r["input"]),
                f"{r['low']:g}",
                f"{r['high']:g}",
                _money(r["median_npv_at_low"]),
                _money(r["median_npv_at_high"]),
                _money(r["npv_swing_usd"]),
                int(r["sites_moved"]),
            ]
            for _, r in tornado.iterrows()
        ],
    )
    scenarios = _table(
        [
            "Comparison",
            "Spearman",
            "Counts as moved at",
            "Sites moved",
            "Largest move",
            "Top 10 kept",
        ],
        [
            [
                r["label"],
                f"{r['spearman']:.3f}",
                f"{r['threshold']}+ places",
                r["moved"],
                r["max_move"],
                r["top_kept"],
            ]
            for _, r in shifts.iterrows()
        ],
    )
    sweep = pd.read_csv(OUT / "revenue_sweep.csv")
    revenue = _table(
        [
            "Other revenue $/kW-yr",
            "Sites likely viable (P50 > 0)",
            "Sites robustly viable (P10 > 0)",
        ],
        [
            [
                _money(r["other_revenue_usd_per_kw_year"]),
                int(r["sites_likely_viable"]),
                int(r["sites_robustly_viable"]),
            ]
            for _, r in sweep.iterrows()
        ],
    )
    by_type = ranking.groupby("building_type")["rank"].median().sort_values()
    types = _table(["Type", "Median rank"], [[t, f"{v:g}"] for t, v in by_type.items()])
    plain = [f"- **{k.replace('_', ' ').capitalize()}.** {v}" for k, v in text.items()]
    lines = [
        "# M4 results (generated)",
        "",
        "Generated by `scripts/report_ranking.py` from `ridgeline rank` "
        f"({run['n_draws']:,} draws, seed {run['seed']}). Do not edit by hand.",
        "All values illustrative; real 2025 dollars.",
        "",
        "## In plain language",
        "",
        *plain,
        "",
        "## Top 10 by robustness (P10 NPV)",
        "",
        *top,
        "",
        "Full table: [`ranking.csv`](ranking.csv).",
        "",
        "## What if sites also earned other revenue?",
        "",
        "Every site gets the same extra $/kW-year (for example demand-response payments, which",
        "this model does not include). No program amount is assumed; this only shows how much",
        "would be needed.",
        "",
        *revenue,
        "",
        "## Sensitivity: tornado (one input at a time)",
        "",
        "![Tornado](tornado.png)",
        "",
        *swings,
        "",
        "## Scenario comparisons (full Monte Carlo, same random draws)",
        "",
        *scenarios,
        "",
        "## Median rank by building type",
        "",
        *types,
        "",
    ]
    (OUT / "results.md").write_text("\n".join(lines))


def main() -> None:
    settings = load_settings()
    src = settings.resolve(settings.paths.cache_dir) / "results"
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("ranking.csv", "tornado.csv", "rank_shifts.csv", "revenue_sweep.csv"):
        shutil.copy(src / name, OUT / name)
    ranking, tornado = pd.read_csv(OUT / "ranking.csv"), pd.read_csv(OUT / "tornado.csv")
    shifts = pd.read_csv(OUT / "rank_shifts.csv")
    info = json.loads((src / "explanations.json").read_text())
    threshold = int(shifts.loc[shifts["label"] == "churn_on_vs_off", "threshold"].iloc[0])
    plot_tornado(tornado, threshold)
    write_results(ranking, tornado, shifts, info)


if __name__ == "__main__":
    main()
