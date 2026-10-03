"""Step 2: look at the data you will actually model on.

    python explore/02_data_tour.py [TICKER]

Each section is independent, so one missing panel does not stop the rest.
Pulls one ticker at a time and a short window across the universe, which is
what the hosted (HTTP range-request) client handles well.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager

import pandas as pd

from statevector import Dataset

TICKER = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
ds = Dataset()
CUT = ds.holdout_cutoff()
pd.set_option("display.width", 160, "display.max_columns", 40)


@contextmanager
def section(title: str):
    print(f"\n{'=' * 8} {title}")
    try:
        yield
    except Exception as e:  # noqa: BLE001 - exploration script, keep going
        print(f"  [skipped: {type(e).__name__}: {e}]")


with section(f"state vector for {TICKER}: columns and null rates"):
    sv = ds.state_vector(TICKER, start="2017-01-01", end=str(CUT - pd.Timedelta(days=1)))
    print(f"  {len(sv):,} rows, {sv['date'].min()} -> {sv['date'].max()}")
    nulls = sv.isna().mean().sort_values(ascending=False)
    print("  null rate by column (nulls are information; check flags first):")
    print(nulls[nulls > 0].round(3).to_string())

with section("control flags: how often each is set (one ticker)"):
    flags = [c for c in sv.columns if c in {
        "snapshot_track_used", "guidance_absent", "options_thin_chain",
        "spread_filtered", "half_life_imputed", "staleness_quarterly"}]
    print(sv[flags].mean().round(3).to_string())

with section("feature distributions, latest pre-holdout cross-section"):
    last_day = ds.trading_days(end=str(CUT - pd.Timedelta(days=1)))[-1]
    xs = ds.state_vector(start=str(last_day), end=str(last_day))
    num = xs.select_dtypes("number")
    print(f"  {len(xs):,} tickers on {last_day}")
    print(num.describe(percentiles=[.01, .5, .99]).T[["count", "mean", "std", "1%", "50%", "99%"]]
          .round(3).to_string())

with section(f"point-in-time: raw vs asof fundamentals for {TICKER}"):
    raw = ds.get("fundamentals_actuals", ticker=TICKER)
    pit = ds.fundamentals(TICKER, asof="2024-03-31")
    print(f"  raw rows (all periods, includes unfiled quarters): {len(raw)}")
    print(f"  asof 2024-03-31 rows (only what was filed by then): {len(pit)}")
    print(f"  latest period visible: {pit['date'].max() if len(pit) else None}")
    print("  filing calendar:")
    print(ds.calendar(TICKER).tail(4).to_string(index=False))

with section(f"options: smile and a protective-put candidate for {TICKER}"):
    sm = ds.smile(TICKER, start="2024-06-01", end="2024-06-30")
    print(sm.tail(3).to_string(index=False))
    chain = ds.options_greeks(TICKER, on="2024-06-21")
    puts = chain[chain["ticker"].str.contains(r"\d{6}P")]
    cols = [c for c in ("ticker", "close", "volume", "delta", "iv") if c in puts.columns]
    print(f"  {len(chain):,} contracts, {len(puts):,} puts on 2024-06-21")
    print(puts[cols].sort_values("volume", ascending=False).head(5).to_string(index=False)
          if "volume" in puts.columns else puts[cols].head(5).to_string(index=False))

with section("sectors and liquidity"):
    sec = ds.sectors()
    print(f"  {len(sec):,} names; columns: {list(sec.columns)}")
    print(sec.head(5).to_string(index=False))
    print(f"  20d ADV for {TICKER}: {ds.adv(TICKER):,.0f}")

with section("benchmark"):
    spx = ds.benchmark("SPX")
    print(spx.tail(3).to_string(index=False))

print(f"\nReminder: holdout starts {CUT}. Keep every training/validation window before it.")
