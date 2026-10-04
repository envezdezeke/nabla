"""Review the 15-stock book on a few dates: names, sector clusters, cash rule.

    python explore/06_sample_holdings.py [--dates 2019-06-28 2020-03-27 2022-06-24 latest]

For each date the weekly decisions are replayed from eight weeks earlier (so
the entry/exit bands see last week's holdings, as in the live book), then the
book is printed with company name, cluster, weight, price and 20-day dollar
volume. Checks:
  * odd names: price under $10 or dollar volume under $100M are marked
  * clusters near the 30% cap (4 or more of 15 names)
  * stress and panic flags on that date (preview of the plan's rule; the cash
    rule is not wired into the model yet)
Reuses the yearly cache in artifacts/cache, so run it after another script has
downloaded the years.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from statevector import Dataset  # noqa: E402

from nabla import data, factors, model, pipeline, regime, sim  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--dates", nargs="+", default=["2019-06-28", "2020-03-27", "2022-06-24", "latest"])
ap.add_argument("--replay-weeks", type=int, default=8)
args = ap.parse_args()

cfg = model.load_config()
ds = Dataset()
last = pd.Timestamp(data.last_trading_day(ds))
dates = [last if d == "latest" else pd.Timestamp(d) for d in args.dates]
start = min(dates) - pd.Timedelta(weeks=args.replay_weeks + 1)
inp = pipeline.load(ds, start.date(), last.date())
idx = inp.close.index
print("data notes:", {k: v for k, v in inp.notes.items() if k != "sector_groups"})
print("clusters:", inp.notes.get("sector_groups"))

names = ds.get("reference_tickers", limit=data.BIG).drop_duplicates("ticker").set_index("ticker")["name"]
spx = data.spx_close(ds)
try:
    sva = ds.state_vector("AAPL", start=str((start - pd.Timedelta(days=800)).date()), end=str(last.date()))
    funding = pd.Series(sva["funding_stress"].values, index=pd.to_datetime(sva["date"])).sort_index()
except Exception as e:  # noqa: BLE001
    print("funding stress unavailable:", e)
    funding = None

for target in dates:
    target = idx[idx <= target][-1]
    w0 = target - pd.Timedelta(weeks=args.replay_weeks)
    reb = [idx[i - 1] for i in sim.rebalance_days(idx) if w0 <= idx[i] <= target]
    sig_dates = [d for d in reb if d < target] + [target]
    sv = data.load_state_vector(ds, data.window_start(w0.date(), 10), target.date(), sig_dates)
    sv_by = {d: g for d, g in sv.groupby("date")}
    held: list[str] = []
    for d in sig_dates:
        i = idx.get_loc(d) + 1
        ft = factors.factor_table(inp.close.iloc[:i].iloc[-sim.YEAR - 2:], inp.volume.iloc[:i].iloc[-sim.YEAR - 2:],
                                  sv_by.get(d, pd.DataFrame(columns=["ticker"])), inp.fund, inp.splits)
        w, detail = model.decide(ft, inp.groups, held, cfg)
        held = list(w.index)

    book = pd.DataFrame({
        "name": names.reindex(w.index).str.slice(0, 28),
        "cluster": inp.groups.reindex(w.index),
        "weight": w.round(4),
        "price": ft["price"].reindex(w.index).round(2),
        "adv20_$M": (ft["adv20"].reindex(w.index) / 1e6).round(0),
        "score": detail["score"].reindex(w.index).round(2),
    }).sort_values("weight", ascending=False)
    book["flag"] = ""
    book.loc[book["price"] < 10, "flag"] += "low-price "
    book.loc[book["adv20_$M"] < 100, "flag"] += "thin "
    counts = book["cluster"].value_counts()
    rep = factors.liquidity_report(ft, **cfg["liquidity"])
    fl = regime.flags_asof(spx, target, funding)

    print(f"\n==================== {target.date()} ====================")
    print(f"liquidity filter: {rep}")
    print(book.to_string())
    print(f"names {len(book)}, invested {w.sum():.2f}")
    print("cluster counts (cap 30% = 4 of 15):", counts.to_dict(),
          "| near cap:", [c for c, n in counts.items() if n >= 4 and c != "other"] or "none")
    print(f"regime (preview): stress={fl.get('stress')} panic={fl.get('panic')} "
          f"below_200dma={fl.get('below_200dma')} vol_pct={fl.get('vol_pct')} "
          f"funding_pct={fl.get('funding_pct')} ret_12m={fl.get('ret_12m')}")

# when would the stress rule have been on? (whole history, weekly)
wf = regime.weekly_flags(spx[spx.index <= last], funding)
on = wf[wf["stress"]]
print("\nweeks with stress on, by year:", on.groupby(on.index.year).size().to_dict())
print("weeks with panic on, by year:", wf[wf["panic"]].groupby(wf[wf["panic"]].index.year).size().to_dict())
