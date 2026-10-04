"""Crowding check: are we just holding the past year's biggest winners?

    python explore/07_crowding_check.py [--dates latest] [--history]

Compares our 15-stock book with a naive momentum book: the 20 liquid names
with the highest plain 12-month return (no skipped month), which is what a
simple momentum-chasing team would hold. More than about half of our book in
that list means we are crowded: if momentum reverses, every such team loses
together.

For each date the weekly decisions are replayed from eight weeks earlier (so
the entry/exit bands see last week's holdings, as in the live book). Overlap
names that rank 11 or worse on our own score are marked "marginal": they are
the swap candidates, since they barely made the book anyway.

--history also prints the overlap at every month-end since 2018 (top 15 by
score without bands, a close approximation) so the latest number has context.
Reuses the yearly cache in artifacts/cache.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from statevector import Dataset  # noqa: E402

from nabla import combine, data, factors, model, pipeline, sim  # noqa: E402
from nabla import clusters  # noqa: E402

NAIVE_N = 20
MARGINAL_RANK = 11
CROWDED_SHARE = 0.5

ap = argparse.ArgumentParser()
ap.add_argument("--dates", nargs="+", default=["latest"])
ap.add_argument("--replay-weeks", type=int, default=8)
ap.add_argument("--history", action="store_true")
ap.add_argument("--history-start", default="2018-01-01")
args = ap.parse_args()

cfg = model.load_config()
ds = Dataset()
last = pd.Timestamp(data.last_trading_day(ds))
dates = [last if d == "latest" else pd.Timestamp(d) for d in args.dates]
start = min(dates + ([pd.Timestamp(args.history_start)] if args.history else []))
start -= pd.Timedelta(weeks=args.replay_weeks + 1)
inp = pipeline.load(ds, start.date(), last.date())
idx = inp.close.index
names = ds.get("reference_tickers", limit=data.BIG).drop_duplicates("ticker").set_index("ticker")["name"]


def table_at(d: pd.Timestamp, sv_by: dict) -> pd.DataFrame:
    i = idx.get_loc(d) + 1
    return factors.factor_table(inp.close.iloc[:i].iloc[-sim.YEAR - 2:], inp.volume.iloc[:i].iloc[-sim.YEAR - 2:],
                                sv_by.get(d, pd.DataFrame(columns=["ticker"])), inp.fund, inp.splits)


def naive_top(d: pd.Timestamp, ft: pd.DataFrame) -> pd.Series:
    """Plain 12-month return among liquid names, top NAIVE_N."""
    i = idx.get_loc(d)
    r12 = inp.close.iloc[i] / inp.close.iloc[i - sim.YEAR] - 1
    ok = ft.index[factors.liquid(ft, **cfg["liquidity"])]
    return r12.reindex(ok).dropna().sort_values(ascending=False)


for target in dates:
    target = idx[idx <= target][-1]
    w0 = target - pd.Timedelta(weeks=args.replay_weeks)
    reb = [idx[i - 1] for i in sim.rebalance_days(idx) if w0 <= idx[i] <= target]
    sig_dates = [d for d in reb if d < target] + [target]
    sv = data.load_state_vector(ds, data.window_start(w0.date(), 10), target.date(), sig_dates)
    sv_by = {d: g for d, g in sv.groupby("date")}
    held: list[str] = []
    for d in sig_dates:
        ft = table_at(d, sv_by)
        w, detail = model.decide(ft, clusters.at(inp.groups, d), held, cfg)
        held = list(w.index)

    r12 = naive_top(target, ft)
    top = list(r12.index[:NAIVE_N])
    our_rank = pd.Series(range(1, len(detail) + 1), index=detail.index)
    naive_rank = pd.Series(range(1, len(r12) + 1), index=r12.index)
    book = pd.DataFrame({
        "name": names.reindex(w.index).str.slice(0, 26),
        "weight": w.round(3),
        "our_rank": our_rank.reindex(w.index),
        "score": detail["score"].reindex(w.index).round(2),
        "ret_12m": r12.reindex(w.index).round(2),
        "naive_rank": naive_rank.reindex(w.index),
    }).sort_values("our_rank")
    book["in_naive_top20"] = book.index.isin(top)
    book["swap_candidate"] = book["in_naive_top20"] & (book["our_rank"] >= MARGINAL_RANK)
    n_over = int(book["in_naive_top20"].sum())

    print(f"\n==================== {target.date()} ====================")
    print(book.to_string())
    print(f"\noverlap with naive 12-month top {NAIVE_N}: {n_over} of {len(book)} "
          f"({n_over / max(len(book), 1):.0%}); crowded if above {CROWDED_SHARE:.0%}: "
          f"{'YES' if n_over > CROWDED_SHARE * len(book) else 'no'}")
    print("swap candidates (overlap and our rank >= %d):" % MARGINAL_RANK,
          list(book.index[book["swap_candidate"]]) or "none")
    # replacements: best-scored names not in the book and not in the naive top 20
    alt = detail[~detail.index.isin(book.index) & ~detail.index.isin(top)].head(5)
    print("next best non-crowded names (by our score):",
          [f"{t} ({s:.2f})" for t, s in alt["score"].items()])
    print("naive top 20:", top)

if args.history:
    me = [g.index[-1] for _, g in pd.Series(idx, index=idx)[idx >= pd.Timestamp(args.history_start)]
          .groupby(idx[idx >= pd.Timestamp(args.history_start)].to_period("M"))]
    me = [d for d in me if idx.get_loc(d) > sim.YEAR]
    sv = data.load_state_vector(ds, data.window_start(me[0].date(), 10), me[-1].date(), me)
    sv_by = {d: g for d, g in sv.groupby("date")}
    rows = []
    for d in me:
        ft = table_at(d, sv_by)
        pool = ft[factors.liquid(ft, **cfg["liquidity"])]
        score = combine.composite(pool, clusters.at(inp.groups, d), cfg["factor_weights"]).sort_values(ascending=False)
        ours = set(score.index[:cfg["book"]["n"]])
        rows.append({"date": d.date(), "overlap": len(ours & set(naive_top(d, ft).index[:NAIVE_N]))})
    h = pd.DataFrame(rows).set_index("date")
    print(f"\nmonth-end overlap of unbanded top {cfg['book']['n']} with naive top {NAIVE_N}:")
    print(h["overlap"].describe().round(1).to_string())
    print("by year (mean):", h.groupby(pd.to_datetime(h.index).year)["overlap"].mean().round(1).to_dict())
    print("last 12 months:", h["overlap"].tail(12).to_dict())
