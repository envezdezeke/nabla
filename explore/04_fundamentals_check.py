"""Check the quality and value inputs against the real data (needs the token).

    python explore/04_fundamentals_check.py

Answers, in order:
  1. What columns does fundamentals_actuals have, and which did we map?
  2. Which quality and value definitions does the mapping produce?
  3. Are quarterly flows quarterly (not year-to-date)? Compare four quarters to a year.
  4. Are per-share figures restated for splits? Look at EPS around AAPL 2020-08-31 and NVDA 2024-06-10.
  5. How long after period end do rows become knowable, and does the filing calendar have times?
  6. Coverage and a sample of quality and value on the last trading day.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from statevector import Dataset  # noqa: E402

from nabla import data, fundamentals as F  # noqa: E402

pd.set_option("display.width", 160, "display.max_columns", 30)
ds = Dataset()

raw = ds.get("fundamentals_actuals", limit=data.BIG)
print("1) columns:", list(raw.columns))
mapping = F.resolve_columns(raw.columns)
print("   mapped:", mapping)
print("   unmapped fields:", [k for k in F.CANDIDATES if k not in mapping])

cal = ds._scan("report_calendar_us").collect().to_pandas()
print("\n5) filing calendar columns:", list(cal.columns))
f, _ = F.prepare(raw, cal)
lag = (f["knowable"] - f["date"]).dt.days
print("   days from period end to knowable:", lag.describe(percentiles=[.1, .5, .9]).round(1).to_dict())
print("   share using the 60-day fallback:", round(float((lag == 60).mean()), 3))

for tk in ("AAPL", "NVDA"):
    g = f[f["ticker"] == tk].sort_values("date").tail(16)
    cols = [c for c in ("date", "knowable", "eps", "sales", "gross_profit", "net_income", "total_assets") if c in g]
    print(f"\n3/4) {tk} last 16 quarters (look for a jump in EPS at the split, and quarterly-sized sales):")
    print(g[cols].to_string(index=False))

asof = data.last_trading_day(ds)
px = data.load_prices(ds, asof - pd.Timedelta(days=10), asof, list(f["ticker"].unique()))
price = data.to_wide(px, "close").iloc[-1]
qv, notes = F.quality_value(f, price, pd.Timestamp(asof) + pd.Timedelta(hours=16), data.load_splits(ds))
print(f"\n2) definitions on {asof}:", notes)
print("6) coverage:", qv.notna().mean().round(3).to_dict())
print(qv.describe(percentiles=[.01, .5, .99]).round(4).to_string())
print("\n   top 10 quality:\n", qv["quality"].nlargest(10).round(4).to_string())
print("\n   top 10 value:\n", qv["value"].nlargest(10).round(4).to_string())
