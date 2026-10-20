"""Run the frozen model on the cached Bloomberg data and write the live book.

    python scripts/bbg_live.py [--asof YYYY-MM-DD]

Reads only artifacts/bbg/ (run scripts/bbg_pull.py first). Writes the book to
artifacts/bbg/live_book.json and live_book.csv (gitignored; never commit them).
Prints aggregates only, never holdings: open the files yourself in a terminal
outside Claude Code (docs/BLOOMBERG_RULES.md, rules 6 and 7).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nabla import live, model  # noqa: E402
from nabla.bloomberg import BBG_DIR, BbgDataset  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", help="decision day (default: last day in the cache)")
    a = ap.parse_args()
    ds = BbgDataset()
    cfg = model.load_config()
    book = live.build_book(ds, cfg, asof=a.asof)
    (BBG_DIR / "live_book.json").write_text(json.dumps(book, indent=1, default=str))
    h = pd.DataFrame(book["holdings"])
    h.to_csv(BBG_DIR / "live_book.csv", index=False)

    cash = float(h.loc[h["ticker"] == "CASHHOLDING", "weight"].sum())
    stocks = h[h["ticker"] != "CASHHOLDING"]
    print(f"model {book['model']}, data through {book['as_of']}")
    print(f"names {len(stocks)}, cash {cash:.1%}, weights sum {h['weight'].sum():.6f}, "
          f"largest weight {stocks['weight'].max():.1%}")
    print("regime flags:", book["regime"])
    print("factor coverage among liquid names:", {k: round(v, 2) for k, v in book["coverage"].items()})
    print("notes:", {k: v for k, v in book["notes"].items() if not isinstance(v, dict)})
    print(f"wrote {BBG_DIR / 'live_book.json'} and live_book.csv (open them yourself; not shown here)")


if __name__ == "__main__":
    main()
