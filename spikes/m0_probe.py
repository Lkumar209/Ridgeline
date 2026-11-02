"""M0 data-feasibility probe (throwaway; not part of the package).

Usage:  python spikes/m0_probe.py <download_dir>

Downloads one MA county's ComStock baseline metadata, two MA building timeseries files and one
county weather file from the OEDI public S3 bucket, then prints the stats quoted in
spikes/m0_data_feasibility.md. Requires pandas + pyarrow.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import pandas as pd

BASE = (
    "https://oedi-data-lake.s3.amazonaws.com/nrel-pds-building-stock/"
    "end-use-load-profiles-for-us-building-stock/2024/comstock_amy2018_release_2/"
)
COUNTY = "G2500170"  # Middlesex County, MA
TS_PREFIX = "timeseries_individual_buildings/by_state/upgrade=0/state=MA"
FILES = {
    "meta.parquet": f"metadata_and_annual_results/by_state_and_county/full/parquet/"
    f"state=MA/county={COUNTY}/MA_{COUNTY}_baseline.parquet",
    "ts_100651.parquet": f"{TS_PREFIX}/100651-0.parquet",
    "ts_100652.parquet": f"{TS_PREFIX}/100652-0.parquet",
    "weather.csv": f"weather/amy2018/{COUNTY}_2018.csv",
}
PEAK = "out.electricity.total.peak_demand..kw"
TOTAL = "out.electricity.total.energy_consumption"


def fetch(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, key in FILES.items():
        path = dest / name
        if not path.exists():
            urllib.request.urlretrieve(BASE + key, path)
        print(f"{name}: {path.stat().st_size:,} bytes")


def main(dest: Path) -> None:
    fetch(dest)
    meta = pd.read_parquet(dest / "meta.parquet")
    unique = meta.drop_duplicates("bldg_id")
    print(f"metadata rows={len(meta):,} cols={meta.shape[1]} unique bldg_id={len(unique):,}")
    print(unique["in.as_simulated_state_name"].value_counts().to_string())
    stats = unique.groupby("in.comstock_building_type")[PEAK].quantile([0.1, 0.5, 0.9]).unstack()
    print(stats.round(0).to_string())
    in_range = unique[PEAK].between(100, 1000).sum()
    print(f"buildings with 100-1000 kW annual peak: {in_range} of {len(unique)}")
    eia = meta["out.utility_bills.electricity_utility_eia_id"].value_counts().head(5)
    print(eia.to_string())

    for name in ("ts_100651.parquet", "ts_100652.parquet"):
        ts = pd.read_parquet(dest / name)
        kw = ts[TOTAL] * 4  # kWh per 15-min interval -> average kW
        print(
            f"{name}: rows={len(ts)} cols={ts.shape[1]} "
            f"first={ts['timestamp'].min()} last={ts['timestamp'].max()} "
            f"peak_kW={kw.max():.1f} mean_kW={kw.mean():.1f} load_factor={kw.mean() / kw.max():.2f}"
        )

    weather = pd.read_csv(dest / "weather.csv")
    print(f"weather rows={len(weather)} cols={list(weather.columns)}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
