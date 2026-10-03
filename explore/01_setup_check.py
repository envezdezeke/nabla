"""Step 1: confirm the data connection and learn the shape of the dataset.

    export SV_DATA_ROOT=https://pop-os.tail01ad.ts.net   # or a local path
    export SV_DATA_TOKEN=<team token>                    # hosted data only
    python explore/01_setup_check.py

Read-only. Prints panels, universe size, date range, and the sealed
holdout cutoff. Nothing here touches data on or after the cutoff.
"""
from __future__ import annotations

import os
import sys

from statevector import Dataset


def main() -> int:
    root = os.environ.get("SV_DATA_ROOT")
    if not root:
        print("SV_DATA_ROOT not set. See docs/GETTING_STARTED.md.")
        return 1
    if root.startswith("http") and not os.environ.get("SV_DATA_TOKEN"):
        print("Hosted data needs SV_DATA_TOKEN (ask the organizers; never commit it).")
        return 1

    ds = Dataset()
    print(f"root: {ds.root}\n")

    print("== panels (name -> rows) ==")
    for name, n in ds.panels().items():
        print(f"  {name:32s} {n:>14,}")

    uni = ds.universe()
    print(f"\n== universe ==\n  {len(uni):,} US tickers, e.g. {uni[:8]}")

    days = ds.trading_days()
    cut = ds.holdout_cutoff()
    print(f"\n== calendar ==\n  trading days {min(days)} -> {max(days)} ({len(days):,})")
    print(f"  SEALED HOLDOUT starts {cut}: never train/validate on dates >= this")

    tk = "AAPL" if "AAPL" in uni else uni[0]
    print(f"\n== {tk} spot check ==")
    print(ds.prices(tk, start="2024-01-01").tail(3).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
