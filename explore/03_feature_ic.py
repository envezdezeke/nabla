"""Step 3: which state-vector features predict forward returns?

The launchpad's suggested first afternoon: rank the universe on a feature,
compare top-decile vs bottom-decile forward returns. For each feature this
reports mean rank-IC (Spearman, per date), its t-stat across dates, and the
top-minus-bottom decile spread.

    python explore/03_feature_ic.py [--start 2022-01-01] [--horizon 21] [--step 5]

Guards against lookahead:
  * prices and signals are both cut at ds.holdout_cutoff() (sealed holdout)
  * forward return = close[t+h]/close[t]-1, rows whose horizon would run past
    the cutoff are dropped, not filled
  * signals are sampled every --step trading days to limit overlap
Treat this as exploration. Overlapping windows inflate t-stats, so rank
features, do not read the t-stat as a significance test.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from statevector import Dataset

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2022-01-01")
ap.add_argument("--horizon", type=int, default=21, help="forward trading days")
ap.add_argument("--step", type=int, default=5, help="sample every N trading days")
args = ap.parse_args()

ds = Dataset()
cut = pd.Timestamp(ds.holdout_cutoff())
end = str((cut - pd.Timedelta(days=1)).date())
print(f"window {args.start} -> {end} (holdout starts {cut.date()})")

px = ds.get("stocks_daily", start=args.start, end=end, limit=200_000_000)[
    ["ticker", "date", "close"]]
px["date"] = pd.to_datetime(px["date"])
px = px.sort_values(["ticker", "date"])
px["fwd"] = px.groupby("ticker")["close"].shift(-args.horizon) / px["close"] - 1
px = px.dropna(subset=["fwd"])

sv = ds.get("state_vector", start=args.start, end=end)
sv["date"] = pd.to_datetime(sv["date"])
dates = sorted(sv["date"].unique())[:: args.step]
sv = sv[sv["date"].isin(dates)]
df = sv.merge(px[["ticker", "date", "fwd"]], on=["ticker", "date"], how="inner")
print(f"{len(df):,} ticker-days, {df['date'].nunique()} dates, {df['ticker'].nunique()} tickers")

skip = {"ticker", "date", "fwd"}
feats = [c for c in df.select_dtypes("number").columns if c not in skip and df[c].nunique() > 5]


def per_date(g: pd.DataFrame, f: str):
    g = g[[f, "fwd"]].dropna()
    if len(g) < 50:
        return None
    ic = g[f].rank().corr(g["fwd"].rank())
    q = pd.qcut(g[f].rank(method="first"), 10, labels=False)
    spread = g.loc[q == 9, "fwd"].mean() - g.loc[q == 0, "fwd"].mean()
    return ic, spread


rows = []
for f in feats:
    res = [r for _, g in df.groupby("date") if (r := per_date(g, f))]
    if len(res) < 10:
        continue
    ic, sp = (np.array(x) for x in zip(*res))
    rows.append({
        "feature": f, "dates": len(ic), "null_rate": df[f].isna().mean(),
        "mean_ic": ic.mean(), "ic_t": ic.mean() / (ic.std(ddof=1) / np.sqrt(len(ic))),
        "hit_rate": (ic > 0).mean(), "top_minus_bottom": sp.mean(),
    })

out = pd.DataFrame(rows).reindex()
out = out.reindex(out["mean_ic"].abs().sort_values(ascending=False).index)
pd.set_option("display.width", 160)
print(f"\nforward horizon: {args.horizon} trading days\n")
print(out.round(4).to_string(index=False))
