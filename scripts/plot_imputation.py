"""Render the M2 figures into docs/m2/ from the experiment CSVs and the cached loads.

Usage: uv run python scripts/plot_imputation.py   (after scripts/evaluate_imputation.py)

Colors are categorical slots 1-3 of the reference palette, validated all-pairs for color
vision deficiency. Aqua is below 3:1 contrast on the surface, so every series is also
direct-labeled and the numbers are tabulated in docs/m2_imputation.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ridgeline.config import REPO_ROOT, load_settings
from ridgeline.data.comstock import load_cached_timeseries
from ridgeline.data.schemas import LOCAL_TZ
from ridgeline.data.sites import read_sites
from ridgeline.data.weather import load_weather
from ridgeline.gaps.experiment import BASELINE, REGRESSION, REGRESSION_PEERS, build_imputers
from ridgeline.gaps.inject import Gap, apply_gap

OUT = REPO_ROOT / "docs" / "m2"
SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
COLORS = {BASELINE: "#2a78d6", REGRESSION: "#eb6834", REGRESSION_PEERS: "#1baf7a"}
LABELS = {
    BASELINE: "Seasonal profile (baseline)",
    REGRESSION: "Regression: weather + time",
    REGRESSION_PEERS: "Regression: weather + time + peers",
}
SHORT = {BASELINE: "Baseline", REGRESSION: "Weather + time", REGRESSION_PEERS: "+ peers"}
EXAMPLE_SITE = "cs-68361"  # MediumOffice in the dev subset
EXAMPLE_GAP = Gap(
    start=datetime(2018, 6, 15, 4, tzinfo=UTC), end=datetime(2018, 8, 15, 4, tzinfo=UTC)
)
EXAMPLE_WINDOW = ("2018-07-02", "2018-07-07")  # Mon-Fri inside the gap, local time


def _style(ax: plt.Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK_2, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _spread(ends: dict[str, float], min_gap: float) -> dict[str, float]:
    """Nudge end-of-line label positions apart so they never overlap."""
    ordered = sorted(ends.items(), key=lambda kv: kv[1])
    placed: dict[str, float] = {}
    last = -np.inf
    for label, y in ordered:
        y = max(y, last + min_gap)
        placed[label] = y
        last = y
    return placed


def plot_example() -> None:
    settings = load_settings()
    cache = settings.resolve(settings.paths.cache_dir) / "comstock"
    sites = read_sites(settings.resolve(settings.paths.sites_file))
    loads = {
        s.site_id: load_cached_timeseries(cache / "timeseries" / f"{s.bldg_id}.parquet")
        for s in sites
    }
    site = next(s for s in sites if s.site_id == EXAMPLE_SITE)
    weather = load_weather(cache / "weather" / f"{site.county_gisjoin}.csv")
    imputers = build_imputers(site, sites, loads, weather, settings.gaps)
    actual = loads[site.site_id]
    masked = apply_gap(actual, EXAMPLE_GAP)

    local = actual.tz_convert(LOCAL_TZ)
    lo, hi = EXAMPLE_WINDOW
    window = (local.index >= pd.Timestamp(lo, tz=LOCAL_TZ)) & (
        local.index < pd.Timestamp(hi, tz=LOCAL_TZ) + pd.Timedelta(days=1)
    )
    fig, ax = plt.subplots(figsize=(9, 5.0), facecolor=SURFACE)
    _style(ax)
    x = local.index[window]
    ax.plot(x, local[window], color=INK, linewidth=2.0, label="Actual (hidden from imputers)")
    ends = {"Actual": float(local[window].iloc[-1])}
    for name, impute in imputers.items():
        filled = impute(masked).tz_convert(LOCAL_TZ)[window]
        ax.plot(x, filled, color=COLORS[name], linewidth=1.5, label=LABELS[name])
        ends[SHORT[name]] = float(filled.iloc[-1])
    for label, y in _spread(ends, min_gap=9.0).items():
        ax.annotate(
            label,
            xy=(x[-1], y),
            xytext=(6, 0),
            textcoords="offset points",
            color=INK_2,
            fontsize=8,
            va="center",
        )
    ax.set_ylabel("kW (15-min average)", color=INK_2, fontsize=9)
    ax.set_title(
        f"{site.building_type} {site.site_id}: one week inside a simulated 61-day summer outage",
        color=INK,
        fontsize=11,
        loc="left",
    )
    ax.legend(
        frameon=False,
        fontsize=8,
        labelcolor=INK_2,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        ncol=2,
    )
    ax.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%a %b %d", tz=LOCAL_TZ))
    fig.text(
        0.01, 0.01, "Illustrative. ComStock modeled building, AMY2018.", color=MUTED, fontsize=8
    )
    fig.tight_layout(rect=(0, 0.03, 0.88, 1))
    fig.savefig(OUT / "example_summer_gap.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_peak_errors() -> None:
    peaks = pd.read_csv(OUT / "monthly_peak_errors.csv")
    covered = peaks[peaks["gap_fraction"] >= 0.5]
    methods = [m for m in (BASELINE, REGRESSION, REGRESSION_PEERS) if m in set(covered["method"])]
    fig, ax = plt.subplots(figsize=(9, 3.8), facecolor=SURFACE)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    rng = np.random.default_rng(0)
    for row, name in enumerate(reversed(methods)):
        err = covered.loc[covered["method"] == name, "peak_error_pct"].to_numpy()
        y = row + rng.uniform(-0.18, 0.18, len(err))
        ax.scatter(err, y, s=10, color=COLORS[name], alpha=0.45, linewidths=0)
        median = float(np.median(err))
        ax.plot([median, median], [row - 0.3, row + 0.3], color=INK, linewidth=2.0)
        ax.annotate(
            f"median {median:+.1f}%",
            xy=(median, row + 0.32),
            ha="center",
            va="bottom",
            fontsize=8,
            color=INK_2,
            bbox={"facecolor": SURFACE, "edgecolor": "none", "pad": 1.0},
        )
    ax.axvline(0, color=MUTED, linewidth=1.0)
    ax.set_yticks(range(len(methods)), [LABELS[m] for m in reversed(methods)], color=INK_2)
    ax.set_xlabel(
        "Imputed minus actual monthly peak, % of actual (months >= 50% inside a gap)",
        color=INK_2,
        fontsize=9,
    )
    ax.set_title(
        "Billing-peak error by method: 40 sites x 6 simulated outages",
        color=INK,
        fontsize=11,
        loc="left",
    )
    fig.text(
        0.01, 0.01, "Illustrative. Negative = demand charge understated.", color=MUTED, fontsize=8
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "monthly_peak_error.png", dpi=150, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    plot_example()
    plot_peak_errors()
