"""Pull what the live model needs from the Bloomberg terminal into artifacts/bbg/.

    python scripts/bbg_pull.py            # plan only: hits each step would cost, nothing requested
    python scripts/bbg_pull.py --run      # request what the cache lacks, within the daily budget

Everything is cached and never requested twice. The daily limit comes from
NABLA_BBG_DAILY_HITS (default 500000); check the school's real caps on DAPI<GO>.
Prints counts only. The data stays in artifacts/bbg/ (docs/BLOOMBERG_RULES.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nabla import bloomberg as B  # noqa: E402

REPLAY_WEEKS = 8


def universe(term: B.Terminal, cache: B.Cache, refresh_days: int = 30) -> list[str]:
    f = cache.dir / "universe.json"
    if f.exists() and (date.today() - date.fromisoformat(json.loads(f.read_text())["pulled"])).days < refresh_days:
        return json.loads(f.read_text())["tickers"]
    df, notes = term.reference([B.INDEX_SPX], ["INDX_MEMBERS"], bulk=True)
    tickers = sorted({B.from_bbg(f"{m.split()[0]} US Equity") for m in df["value"]})
    f.write_text(json.dumps({"pulled": date.today().isoformat(), "index": B.INDEX_SPX, "tickers": tickers}))
    print(f"universe: {len(tickers)} index members ({notes['hits']} hits)")
    return tickers


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true", help="send requests (default: plan only)")
    ap.add_argument("--asof", help="last day to pull (default: last completed trading day)")
    a = ap.parse_args()

    end = date.fromisoformat(a.asof) if a.asof else B.last_completed_day()
    px_start = end - timedelta(weeks=REPLAY_WEEKS + 1) - timedelta(days=int(260 * 1.5) + 10) - timedelta(days=10)
    est_start = end - timedelta(weeks=REPLAY_WEEKS + 1) - timedelta(days=45)
    cache = B.Cache()
    budget = B.Budget()
    print(f"as of {end}; budget {budget.limit:,}/day, {budget.used():,} used today")

    with B.Terminal(budget) as term:
        tickers = universe(term, cache) if a.run or (cache.dir / "universe.json").exists() else []
        if not tickers:
            print("plan needs the universe (about 500 hits): run with --run once, or accept the BDS call.")
            return
        steps = [
            ("prices+volume", tickers, B.PRICE_FIELDS, px_start, None, "DAILY"),
            ("SPX history", [B.INDEX_SPX], ["PX_LAST"], B.HISTORY_START, None, "DAILY"),
            ("EPS estimates", tickers, [B.EST_FIELD], est_start, B.EST_OVERRIDE, "DAILY"),
            ("fundamentals", tickers, B.FUND_FIELDS + ["ANNOUNCEMENT_DT"], B.FUND_START, None, "QUARTERLY"),
        ]
        total = 0
        for name, ts, fields, start, ov, per in steps:
            n = B.plan_history(cache, ts, fields, start, end, ov, per)
            total += n
            print(f"  plan {name:14s} {len(ts):4d} securities, {len(fields):2d} fields: ~{n:>9,} hits")
        print(f"  plan total: ~{total:,} hits (budget left today {budget.remaining():,})")
        if not a.run:
            return
        for name, ts, fields, start, ov, per in steps:
            r = B.pull_history(term, cache, ts, fields, start, end, ov, per)
            print(f"  {name}: {r['requests']} requests, {r['hits']:,} hits, "
                  f"{len(r['bad_securities'])} unknown securities, bad fields {sorted(r['bad_fields'])}")
            if r["stopped"]:
                print(f"  STOPPED: {r['stopped']}. Rerun tomorrow; cached ranges are skipped.")
                return
        # next announcement dates (current snapshot, refreshed at most every 3 days)
        f = cache.dir / "expected_report.json"
        if not f.exists() or (date.today() - date.fromisoformat(json.loads(f.read_text())["pulled"])).days >= 3:
            df, n = term.reference([B.to_bbg(t) for t in tickers], ["EXPECTED_REPORT_DT"])
            new = pd.DataFrame({"ticker": df["security"].map(B.from_bbg), "date": pd.Timestamp(date.today()),
                                "value": pd.to_datetime(df["value"], errors="coerce")})
            cache.write("EXPECTED_REPORT_DT", new)
            f.write_text(json.dumps({"pulled": date.today().isoformat()}))
            print(f"  expected report dates: {len(new)} names, {n['hits']} hits")
        print(f"done; {budget.used():,} hits used today")


if __name__ == "__main__":
    main()
