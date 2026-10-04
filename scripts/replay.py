"""Run decide() for every trading day in a window and write the records (JSON lines).

    python scripts/replay.py --start 2026-08-24 --end 2026-09-21

This is what the judges' replay produces, one record per day ("rebalance" on the
last trading day of each week, "hold" otherwise). Writes artifacts/replay.jsonl.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statevector import Dataset  # noqa: E402

from nabla import data  # noqa: E402
from nabla import decide as dc  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()
    ds = Dataset()
    days = [d for d in data.trading_days(ds) if args.start <= str(d) <= args.end]
    out = ROOT / "artifacts" / "replay.jsonl"
    out.parent.mkdir(exist_ok=True)
    with out.open("w") as f:
        for d in days:
            rec = dc.decide(d, ds=ds)
            f.write(json.dumps(rec) + "\n")
            names = ", ".join(f"{h['ticker']} {h['weight']:.3f}" for h in rec["target_holdings"][:4])
            print(f"{d}  {rec['action']:9s} exec {rec['execution_time'][:10]}  {names} ...", flush=True)
    print(f"wrote {out}")
