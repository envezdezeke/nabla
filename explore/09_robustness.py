"""Overnight robustness tests on the shipped model (config/model.json). Measures only.

    python explore/09_robustness.py [--seeds 20] [--only fills,random,years,starts,clusters]

Window: config start to the cutoff minus the held-back months (as run_backtest.py).
  fills     trades at the next open instead of the close (the replay's convention)
  random    N random books (persistent random scores, same bands, caps, costs, cash dial)
  years     calendar-year returns: model vs equal-weight liquid universe vs SPX
  starts    annualized return from each January 2018..2022 to the end (sliced from the full run)
  clusters  return clusters refit every January on the prior year (vs fit once before 2018)
Writes artifacts/robustness.json and prints tables.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from statevector import Dataset  # noqa: E402

from nabla import data, model, pipeline, regime, sim  # noqa: E402

spec = importlib.util.spec_from_file_location("audit", ROOT / "scripts" / "audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

ap = argparse.ArgumentParser()
ap.add_argument("--seeds", type=int, default=20)
ap.add_argument("--only", default="fills,random,years,starts,clusters")
args = ap.parse_args()
want = set(args.only.split(","))

cfg = model.load_config()
bt = cfg["backtest"]
ds = Dataset()
days = data.trading_days(ds)
end = pd.Timestamp(days[-1]) - pd.Timedelta(days=30) - pd.DateOffset(months=bt["holdback_months"])
start = pd.Timestamp(bt["start"])
inp = pipeline.load(ds, start.date(), end.date())
dates = inp.close.index
sig = [dates[i - 1] for i in sim.rebalance_days(dates)] + [dates[dates.searchsorted(start) - 1]]
sv = data.load_state_vector(ds, data.window_start(start.date(), 10), end.date(), sig)
spx_px = data.spx_close(ds)
wf = regime.weekly_flags(spx_px.loc[:end])
print(f"window {start.date()} -> {end.date()}, model {cfg['version']}", flush=True)


def run(name, strat, **kw):
    print(f"\n== {name}", flush=True)
    c = kw.pop("cfg", cfg)
    return sim.run(inp.close, inp.volume, sv, strat, start, end, bt["cost_model"], bt["book_value"],
                   fund=inp.fund, splits=inp.splits, liquidity=c["liquidity"], cost_cfg=c.get("costs"),
                   no_trade_band=kw.pop("band", c["book"].get("no_trade_band")), **kw)


def summary(res):
    m = sim.metrics(res["daily"])
    m.update(audit.capm(res["daily"]["ret"], spx_px.pct_change()))
    return {k: m[k] for k in ["ann_return", "ann_vol", "sharpe", "max_drawdown", "beta", "alpha_ann",
                              "alpha_t", "turnover_per_year", "cost_total", "roll21_p05"]}


def with_cash(fn):
    """Same stress cash dial as model.decide, so random books face the model's rules."""
    sc = float(cfg.get("regime", {}).get("stress_cash") or 0.0)

    def g(ft, held, sig):
        w = fn(ft, held, sig)
        return w * (1.0 - sc) if sc and regime.flags_at(wf, sig).get("stress") else w
    return g


out = {"window": [str(start.date()), str(end.date())], "model": cfg["version"]}
base = run("base (close fills)", model.strategy(inp.groups, cfg, wf))
out["base"] = summary(base)

if "fills" in want:
    raw = data.load_opens(ds, data.window_start(start.date(), 300), end.date())
    raw_open = data.to_wide(raw, "open").reindex_like(inp.close)
    px = data.load_prices(ds, data.window_start(start.date(), 300), end.date())
    raw_close = data.to_wide(px, "close").reindex_like(inp.close)
    opn = data.adjust_like(raw_open, raw_close, inp.close)
    res = run("next-open fills", model.strategy(inp.groups, cfg, wf), open_=opn)
    out["next_open"] = summary(res)
    d = pd.concat([base["daily"]["ret"], res["daily"]["ret"]], axis=1, keys=["close", "open"]).dropna()
    reb = base["books"]["date"]
    out["next_open"]["rebalance_day_gain_bps"] = float((d.loc[d.index.isin(reb), "open"]
                                                       - d.loc[d.index.isin(reb), "close"]).mean() * 1e4)

if "random" in want:
    rnd = {}
    for s in range(args.seeds):
        r = run(f"random seed {s}", with_cash(audit.random_strategy(inp.groups, cfg, s)))
        rnd[s] = summary(r)
    rr = pd.DataFrame(rnd).T
    out["random"] = {"n": len(rr), "ann_return": rr["ann_return"].describe().to_dict(),
                     "sharpe": rr["sharpe"].describe().to_dict(),
                     "model_beats_return": int((rr["ann_return"] < out["base"]["ann_return"]).sum()),
                     "model_beats_sharpe": int((rr["sharpe"] < out["base"]["sharpe"]).sum()),
                     "cash_dial_applied": bool(cfg.get("regime", {}).get("stress_cash"))}

if want & {"years", "starts"}:
    ew = run("equal-weight liquid", model.equal_weight_liquid(cfg), band=None)
    rets = pd.DataFrame({"model": base["daily"]["ret"], "ew": ew["daily"]["ret"]})
    rets["spx"] = spx_px.pct_change().reindex(rets.index).fillna(0.0)
    if "years" in want:
        yr = (1 + rets).groupby(rets.index.year).prod() - 1
        out["years"] = yr.round(4).to_dict(orient="index")
        out["years_model_beats_ew"] = int((yr["model"] > yr["ew"]).sum())
        out["years_model_beats_spx"] = int((yr["model"] > yr["spx"]).sum())
        out["years_n"] = int(len(yr))
    if "starts" in want:
        st = {}
        for y in range(2018, 2023):
            r = rets.loc[f"{y}-01-01":]
            ann = (1 + r).prod() ** (252 / len(r)) - 1
            st[y] = ann.round(4).to_dict()
        out["starts"] = st

if "clusters" in want:
    by_year = {}
    for y in range(start.year, end.year + 1):
        by_year[y] = data.return_clusters(inp.close.loc[:pd.Timestamp(f"{y}-01-01")])
    strat_y = {y: model.strategy(g, cfg, wf) for y, g in by_year.items()}

    def yearly(ft, held, sig):
        return strat_y[pd.Timestamp(sig).year](ft, held, sig)
    res = run("clusters refit yearly", yearly)
    out["clusters_yearly"] = summary(res)
    out["clusters_yearly"]["unclustered_by_year"] = {y: int((g == "other").sum()) for y, g in by_year.items()}

Path(ROOT / "artifacts" / "robustness.json").write_text(json.dumps(out, indent=2, default=str))
print(json.dumps(out, indent=2, default=str))
