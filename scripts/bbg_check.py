"""Check the Terminal link: python scripts/bbg_check.py [TICKER ...]

Pulls a few reference fields, a week of daily history and a live quote, reports
row counts, and saves each pull under artifacts/bbg/. Needs the Terminal logged in on
this machine and blpapi installed.
"""
import sys
from datetime import date, timedelta

from nabla import bloomberg as bbg

tickers = sys.argv[1:] or ["AAPL", "MSFT", "NVDA"]
with bbg.Terminal() as t:
    ref = t.reference(tickers, ["NAME", "GICS_SECTOR_NAME", "PX_LAST", "CUR_MKT_CAP", "BETA_ADJ_OVERRIDABLE"])
    hist = t.history(tickers, ["PX_LAST", "PX_VOLUME"], date.today() - timedelta(days=7), date.today())
    live = t.snapshot(tickers)
for name, df in (("reference", ref), ("history", hist), ("live", live)):
    print(f"\n{name} (pulled {df.attrs['pulled_at']})\n{df.to_string()}")
    print("saved", bbg.save(df, name))
