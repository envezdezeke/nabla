"""Fit the yearly consensus clusters on the real data and freeze them in config/clusters.json.

    python scripts/fit_clusters.py [--first-year 2018]

Each year's groups use only prices before January 1 of that year. Prints how
stable the groups are from one year to the next (adjusted Rand index; 1 = same
grouping, 0 = chance) next to the old single-seed k-means, and how many names
stay unclustered. Commit config/clusters.json afterwards so the backtest, the
live book and /decide all use the same frozen groups.
"""
from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statevector import Dataset  # noqa: E402

from nabla import clusters, data  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--first-year", type=int, default=2018)
    args = ap.parse_args()
    ds = Dataset()
    last = data.last_trading_day(ds)
    years = list(range(args.first_year, last.year + 1))
    px = data.load_prices(ds, date(args.first_year - 4, 1, 1), last, ds.universe())
    close, volume = data.to_wide(px, "close"), data.to_wide(px, "volume")
    close, _, _ = data.split_adjust(close, volume, data.load_splits(ds))

    sched, old = {}, {}
    for y in years:
        sched[y] = clusters.fit(close, date(y, 1, 1))
        prior = close.loc[close.index < pd.Timestamp(date(y, 1, 1))]
        old[y] = data.return_clusters(prior)
        n_other = int((sched[y] == "other").sum())
        sizes = sched[y][sched[y] != "other"].value_counts()
        print(f"{y}: groups {sizes.min()}-{sizes.max()} names, unclustered {n_other} "
              f"(old method {int((old[y] == 'other').sum())})", flush=True)

    print("\nyear-to-year agreement (adjusted Rand; higher = more stable)")
    print("  year   consensus   old single k-means")
    for a, b in zip(years, years[1:]):
        print(f"  {b}   {clusters.adjusted_rand(sched[a], sched[b]):9.2f}   "
              f"{clusters.adjusted_rand(old[a], old[b]):9.2f}")

    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                            cwd=ROOT).stdout.strip()
    digest = hashlib.sha256(pd.util.hash_pandas_object(close.iloc[-5:].fillna(0)).values.tobytes()).hexdigest()[:12]
    meta = {"method": "consensus k-means (seeds x windows) + average-linkage cut, refit each Jan 1 on prior data",
            "params": clusters.DEFAULTS, "data_through": str(last), "git_commit": commit, "data_hash": digest}
    clusters.save(sched, meta)
    print(f"\nwrote {clusters.CONFIG}")
