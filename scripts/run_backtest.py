"""Offline v1 backtest: weekly loop with costs vs equal-weight liquid universe and SPX.

    python scripts/run_backtest.py [--cost-model plan|flat] [--include-holdback]

Window: config backtest.start to the SDK holdout cutoff, minus the held-back
months (untouched until the go/no-go). Writes artifacts/backtest_v1.json.
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

from nabla import data, model, pipeline, sim  # noqa: E402

PERIODS = {"2018Q4": ("2018-10-01", "2018-12-31"), "2020": ("2020-01-01", "2020-12-31"),
           "2022": ("2022-01-01", "2022-12-31")}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-model", choices=["plan", "flat"])
    ap.add_argument("--include-holdback", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "backtest_v1.json"))
    args = ap.parse_args()

    cfg = model.load_config()
    bt = cfg["backtest"]
    cost_model = args.cost_model or bt["cost_model"]
    ds = Dataset()
    days = data.trading_days(ds)
    cutoff = pd.Timestamp(days[-1]) - pd.Timedelta(days=30)  # SDK sealed holdout
    end = cutoff if args.include_holdback else cutoff - pd.DateOffset(months=bt["holdback_months"])
    start = pd.Timestamp(bt["start"])
    print(f"backtest {start.date()} -> {end.date()} (holdout starts {cutoff.date()}, cost model {cost_model})")

    inp = pipeline.load(ds, start.date(), end.date())
    print("data notes:", inp.notes)
    dates = inp.close.index
    sig_dates = [dates[i - 1] for i in sim.rebalance_days(dates)] + [dates[dates.searchsorted(start) - 1]]
    sv = data.load_state_vector(ds, data.window_start(start.date(), 10), end.date(), sig_dates)

    results, v1_days = {}, None
    (ROOT / "artifacts").mkdir(exist_ok=True)
    for name, strat in {"v1": model.strategy(inp.groups, cfg),
                        "ew_liquid": model.equal_weight_liquid(cfg)}.items():
        res = sim.run(inp.close, inp.volume, sv, strat, start, end, cost_model, bt["book_value"])
        results[name] = {**sim.metrics(res["daily"]), "periods": sim.period_returns(res["daily"], PERIODS),
                         "avg_names": float(res["books"]["names"].mean())}
        if name == "v1":
            res["daily"].to_csv(ROOT / "artifacts" / "backtest_v1_daily.csv")
            v1_days = res["daily"].index
    spx = data.spx_close(ds)
    if len(spx):
        r = spx.pct_change().reindex(v1_days).fillna(0.0).to_frame("ret").assign(turnover=0.0, cost=0.0)
        results["spx"] = {**sim.metrics(r), "periods": sim.period_returns(r, PERIODS)}

    table = pd.DataFrame({k: {m: v for m, v in d.items() if m != "periods"} for k, d in results.items()})
    print(table.round(4).to_string())
    print(pd.DataFrame({k: d["periods"] for k, d in results.items()}).round(4).to_string())
    out = {"config": cfg, "window": [str(start.date()), str(end.date())], "cost_model": cost_model,
           "notes": inp.notes, "results": results}
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
