"""Compute the live book from the newest data and freeze it to config/book.json.

    python scripts/build_book.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statevector import Dataset  # noqa: E402

from nabla import live, model  # noqa: E402

if __name__ == "__main__":
    book = live.build_book(Dataset(), model.load_config())
    out = ROOT / "config" / "book.json"
    out.write_text(json.dumps(book, indent=2, default=str))
    w = sum(h["weight"] for h in book["holdings"])
    print(f"as of {book['as_of']}: {len(book['holdings'])} names, weights sum {w:.6f}")
    print("factor coverage among liquid names:", book["coverage"])
    for h in book["holdings"]:
        print(f"  {h['ticker']:8s} {h['weight']:.4f}")
    print(f"wrote {out}")
