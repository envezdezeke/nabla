"""Fill (or extend) the local data store from the Bloomberg Terminal.

  python scripts/bbg_ingest.py --full                 # 2014-01-01 to today, whole universe
  python scripts/bbg_ingest.py                        # daily update: day after the last stored day to today
  python scripts/bbg_ingest.py --start 2026-06-01   # overlap check window

Needs the Terminal logged in on this machine and blpapi installed.
Output goes to $NABLA_DATA_ROOT (default artifacts/bbg), which git ignores.
"""
import argparse
import json
import os
from datetime import date, timedelta
from pathlib import Path

from nabla import bloomberg as bbg, ingest, store

ap = argparse.ArgumentParser()
ap.add_argument("--full", action="store_true", help="start at 2014-01-01")
ap.add_argument("--start", type=date.fromisoformat)
ap.add_argument("--end", type=date.fromisoformat, default=date.today())
ap.add_argument("--universe", help="file with one ticker per line (default: names in config/clusters.json)")
ap.add_argument("--root", default=os.environ.get("NABLA_DATA_ROOT") or str(store.DEFAULT_ROOT))
a = ap.parse_args()

root = Path(a.root)
if a.universe:
    tickers = [t.strip() for t in Path(a.universe).read_text().splitlines() if t.strip()]
else:  # latest frozen cluster fit lists the universe
    fit = json.loads(Path("config/clusters.json").read_text())["years"]
    tickers = sorted(fit[max(fit)])
if a.start:
    start = a.start
elif a.full or not (root / "data").is_dir():
    start = date(2014, 1, 1)
else:
    start = store.Store(root).trading_days()[-1] + timedelta(days=1)  # never re-request cached days

print(f"{len(tickers)} tickers, {start} to {a.end} -> {root}")
with bbg.Terminal() as t:
    print(ingest.run(t, tickers, start, a.end, root))
