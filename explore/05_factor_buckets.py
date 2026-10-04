"""Five-bucket test for each of the five factors (and the composite).

    python explore/05_factor_buckets.py [--start 2018-01-01] [--horizon 21] [--freq M]

On each test date (month-ends by default) liquid stocks are sorted into five
buckets by each factor's sector z-score, and the next month's average return
is recorded per bucket. Returns start the day after the signal (like trading
at the next open). The last six months before the holdout stay untouched, as
the plan requires, so they remain available for the go/no-go.

Writes artifacts/factor_buckets.json and prints a verdict per factor:
  ok, backwards, not_monotone, one_year, too_good (possible leak), no_data.
Monthly windows do not overlap, so the t-stat is roughly honest; with about
90 months only clear effects stand out.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from statevector import Dataset  # noqa: E402

from nabla import combine, data, diagnostics as D, factors, model, pipeline  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--start", default="2018-01-01")
ap.add_argument("--horizon", type=int, default=21)
ap.add_argument("--freq", default="M", help="M = month-ends, W = weekly")
ap.add_argument("--include-holdback", action="store_true")
args = ap.parse_args()

cfg = model.load_config()
ds = Dataset()
days = data.trading_days(ds)
cutoff = pd.Timestamp(days[-1]) - pd.Timedelta(days=30)
end = cutoff if args.include_holdback else cutoff - pd.DateOffset(months=cfg["backtest"]["holdback_months"])
print(f"signals {args.start} -> {end.date()}, forward {args.horizon} trading days")

inp = pipeline.load(ds, pd.Timestamp(args.start).date(), end.date())
close = inp.close
idx = close.index[close.index >= pd.Timestamp(args.start)]
grp = idx.to_period(args.freq)
test_dates = [d for d, nxt in zip(idx[:-1], grp[1:] != grp[:-1]) if nxt]
# keep dates whose forward window ends before the cutoff (no peeking past the data we test on)
pos = {d: close.index.get_loc(d) for d in test_dates}
test_dates = [d for d in test_dates if pos[d] + 1 + args.horizon < len(close.index)
              and close.index[pos[d] + 1 + args.horizon] <= end]
print(f"{len(test_dates)} test dates; data notes: {inp.notes}")

sv = data.load_state_vector(ds, data.window_start(pd.Timestamp(args.start).date(), 10), end.date(), test_dates)
sv_by = {d: g for d, g in sv.groupby("date")}
fwd = D.forward_returns(close, test_dates, args.horizon)

names = factors.FACTORS
z = {f: {} for f in names + ["composite"]}
for d in test_dates:
    i = close.index.get_loc(d) + 1
    ft = factors.factor_table(close.iloc[:i].iloc[-254:], inp.volume.iloc[:i].iloc[-254:],
                              sv_by.get(d, pd.DataFrame(columns=["ticker"])), inp.fund, inp.splits)
    zs = D.factor_z(ft, inp.groups, cfg["liquidity"], names)
    for f in names:
        z[f][d] = zs[f]
    pool = ft[factors.liquid(ft, **cfg["liquidity"])]
    z["composite"][d] = combine.composite(pool, inp.groups, cfg["factor_weights"])

report = {}
for f in names + ["composite"]:
    report[f] = D.summarize(D.quintile_table(z[f], fwd))

pd.set_option("display.width", 170)
cols = ["dates", "avg_names", "q1", "q2", "q3", "q4", "q5", "q5_minus_q1", "spread_t",
        "monotonic", "mean_ic", "years_positive", "flags"]
table = pd.DataFrame(report).T.reindex(columns=cols)
print("\nAverage next-month return by bucket (1 = lowest score, 5 = highest):\n")
print(table.to_string(float_format=lambda x: f"{x:.4f}"))
print("\nSpread (bucket 5 - bucket 1) by year:")
for f, r in report.items():
    print(f"  {f:18s} {r.get('spread_by_year')}")
failing = [f for f in names if report[f]["flags"] != ["ok"]]
print("\nFlag for Ezekiel:", failing or "none, all five point the right way")

(ROOT / "artifacts").mkdir(exist_ok=True)
(ROOT / "artifacts" / "factor_buckets.json").write_text(json.dumps(report, indent=2, default=str))
