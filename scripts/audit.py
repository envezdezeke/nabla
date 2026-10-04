"""Is v1's edge skill, market exposure, or luck? Runs the leak and robustness tests.

    python scripts/audit.py                    # all tests, 2018 -> cutoff minus holdback
    python scripts/audit.py --start 2023-01-01 --only base,random,delay

Tests (each is a full weekly backtest with the plan's costs and the no-trade band):
  base      v1 as configured
  capm      beta and annualized alpha of v1 vs SPX (daily regression, free)
  random    5 books of 15 random liquid names each week, same bands and caps
            (v1 should beat most of them; if not, the scores add nothing)
  delay     signals one extra day old (should hurt a little; a big gain = leak)
  cost2x    double trading costs
  drop_X    composite without factor X (does each factor earn its place?)
  ladder    rung 1 (as v1), rung 2 (+ panic momentum weight), rung 3 (+ 25% cash in stress)
Writes artifacts/audit.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statevector import Dataset  # noqa: E402

from nabla import book, data, factors, model, pipeline, regime, sim  # noqa: E402


def random_strategy(groups, cfg, seed):
    """Each ticker gets one fixed random score per seed, so the random book is as
    persistent as a real factor book (a fresh draw every week would churn the
    whole book and mostly measure costs)."""
    def fn(ft, held, _sig):
        pool = ft[factors.liquid(ft, **cfg["liquidity"])]
        score = pd.Series([np.random.default_rng([seed, *map(ord, t)]).random() for t in pool.index],
                          index=pool.index)
        b = cfg["book"]
        picks = book.select(score, groups, held, n=b["n"], exit_rank=b["exit_rank"], sector_cap=b["sector_cap"])
        return book.weights(picks, pool["days_to_next_report"], max_name=b["max_name"],
                            earnings_cap=b["earnings_cap"], earnings_days=b["earnings_days"])
    return fn


def capm(port: pd.Series, mkt: pd.Series) -> dict:
    x = pd.concat([port, mkt], axis=1, keys=["p", "m"], sort=True).dropna()
    beta = float(np.cov(x["p"], x["m"])[0, 1] / x["m"].var())
    alpha_daily = float(x["p"].mean() - beta * x["m"].mean())
    resid = x["p"] - beta * x["m"]
    return {"beta": beta, "alpha_ann": alpha_daily * 252,
            "alpha_t": float(alpha_daily / (resid.std() / np.sqrt(len(x)))),
            "corr": float(x["p"].corr(x["m"]))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--only", help="comma list of: base,random,delay,cost2x,drop,ladder")
    ap.add_argument("--seeds", type=int, default=5)
    args = ap.parse_args()
    want = set((args.only or "base,random,delay,cost2x,drop").split(","))

    cfg = model.load_config()
    bt = cfg["backtest"]
    ds = Dataset()
    days = data.trading_days(ds)
    end = pd.Timestamp(days[-1]) - pd.Timedelta(days=30) - pd.DateOffset(months=bt["holdback_months"])
    start = pd.Timestamp(args.start or bt["start"])
    inp = pipeline.load(ds, start.date(), end.date())
    dates = inp.close.index
    sig = [dates[i - k] for i in sim.rebalance_days(dates) for k in (1, 2)]
    sig += [dates[dates.searchsorted(start) - k] for k in (1, 2)]
    sv = data.load_state_vector(ds, data.window_start(start.date(), 10), end.date(), sig)
    spx_px = data.spx_close(ds)
    spx = spx_px.pct_change()
    wf = regime.weekly_flags(spx_px.loc[:end])

    def run(name, strat, **kw):
        print(f"\n== {name}", flush=True)
        c = kw.pop("cfg", cfg)
        res = sim.run(inp.close, inp.volume, sv, strat, start, end, bt["cost_model"], bt["book_value"],
                      fund=inp.fund, splits=inp.splits, liquidity=c["liquidity"],
                      cost_cfg=kw.pop("cost_cfg", c.get("costs")),
                      no_trade_band=c["book"].get("no_trade_band"), **kw)
        m = sim.metrics(res["daily"])
        m.update(capm(res["daily"]["ret"], spx))
        return m

    out = {}
    if "base" in want:
        out["base"] = run("base", model.strategy(inp.groups, cfg, wf))
    if "ladder" in want:  # plan v5 ablation rungs 1-3, each must beat the one before
        for name, rg in {"rung1_v1": {"panic_momentum": False, "stress_cash": 0.0},
                         "rung2_panic": {"panic_momentum": True, "stress_cash": 0.0},
                         "rung3_panic_cash": {"panic_momentum": True, "stress_cash": 0.25},
                         "cash_only": {"panic_momentum": False, "stress_cash": 0.25}}.items():
            c = json.loads(json.dumps(cfg))
            c["regime"] = {**c.get("regime", {}), **rg}
            out[name] = run(name, model.strategy(inp.groups, c, wf), cfg=c)
        share = wf.loc[start:end, ["stress", "panic"]].mean()
        print(f"weeks flagged: stress {share['stress']:.0%}, panic {share['panic']:.0%}")
    if "random" in want:
        for s in range(args.seeds):
            out[f"random_{s}"] = run(f"random seed {s}", random_strategy(inp.groups, cfg, s))
    if "delay" in want:
        out["delay"] = run("delay 1 day", model.strategy(inp.groups, cfg, wf), signal_lag=2)
    if "cost2x" in want:
        cc = dict(cfg.get("costs") or {"half_spread_bps": [5, 10, 20], "impact_k": 1.0, "max_adv_pct": 0.01})
        cc["half_spread_bps"] = [2 * x for x in cc["half_spread_bps"]]
        cc["impact_k"] = 2 * cc["impact_k"]
        out["cost2x"] = run("2x costs", model.strategy(inp.groups, cfg, wf), cost_cfg=cc)
    if "drop" in want:
        for f in cfg["factor_weights"]:
            c = json.loads(json.dumps(cfg))
            c["factor_weights"][f] = 0.0
            out[f"drop_{f}"] = run(f"drop {f}", model.strategy(inp.groups, c, wf), cfg=c)

    cols = ["total_return", "ann_return", "ann_vol", "sharpe", "max_drawdown", "beta", "alpha_ann",
            "alpha_t", "turnover_per_year", "cost_total", "roll21_median", "roll21_p05"]
    table = pd.DataFrame(out).T[cols]
    rnd = table[table.index.str.startswith("random")]
    if len(rnd) and "base" in table.index:
        better = int((rnd["total_return"] < table.loc["base", "total_return"]).sum())
        print(f"\nv1 beats {better} of {len(rnd)} random books on total return")
    pd.set_option("display.width", 200)
    print(table.astype(float).round(3).to_string())
    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts" / "audit.json").write_text(json.dumps(out, indent=2, default=str))
    print("wrote artifacts/audit.json")


if __name__ == "__main__":
    main()
