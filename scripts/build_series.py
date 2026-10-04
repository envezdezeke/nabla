"""Precompute the decision series the judges request (POST /decisions) and freeze
it in config/series.json, so the API answers instantly and still answers if the
data server later becomes unreachable.

    python scripts/build_series.py                       # 2026-08-24 -> 2026-09-21 (decisions.yaml)
    python scripts/build_series.py --start 2026-08-24 --end 2026-09-21
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statevector import Dataset  # noqa: E402

from nabla import decide  # noqa: E402

OUT = ROOT / "config" / "series.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-08-24")
    ap.add_argument("--end", default="2026-09-21")
    args = ap.parse_args()
    t0 = time.time()
    body = decide.series(args.start, args.end, ds=Dataset())
    stored = json.loads(OUT.read_text()) if OUT.exists() else {}
    stored[f"{body['start']}:{body['end']}"] = body
    OUT.write_text(json.dumps(stored, indent=1, default=str))
    for r in body["series"]:
        names = ", ".join(f"{h['ticker']} {h['weight']:.3f}" for h in r["target_holdings"][:4])
        print(f"{r['decision_id']}  cutoff {r['information_cutoff']}  exec {r['execution_time']}  "
              f"{len(r['target_holdings'])} legs  {names} ...")
    print(f"wrote {OUT} ({len(body['series'])} decisions, {time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
