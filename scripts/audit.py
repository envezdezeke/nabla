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
  returns   total-return variants vs base, each one change (pre-registered rule in docs/AUDIT.md):
            no_cash (stress cash 0), beta_tilt (beta weight 0.5), mom2 (momentum weight 2),
            pead (earnings-surprise factor weight 1), all4 (all four, informational only).
            Each gets a paired block-bootstrap p-value and Newey-West t on its gap vs base,
            and a deflated Sharpe over all variants tried.
  holdout   base vs --candidate (default pead) on the six held-back months only. Run ONCE.
  ic        weekly rank IC of each factor and the composite vs next-week returns
            (all liquid names, so far more power than a 15-name book), Newey-West t
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

from nabla import book, clusters, combine, data, factors, model, pipeline, regime, sim, stats  # noqa: E402


def random_strategy(groups, cfg, seed):
    """Each ticker gets one fixed random score per seed, so the random book is as
    persistent as a real factor book (a fresh draw every week would churn the
    whole book and mostly measure costs)."""
    from nabla import clusters

    def fn(ft, held, sig):
        g = clusters.at(groups, sig)
        pool = ft[factors.liquid(ft, **cfg["liquidity"])]
        score = pd.Series([np.random.default_rng([seed, *map(ord, t)]).random() for t in pool.index],
                          index=pool.index)
        b = cfg["book"]
        picks = book.select(score, g, held, n=b["n"], exit_rank=b["exit_rank"], sector_cap=b["sector_cap"])
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


VARIANTS = {"no_cash": {"regime": {"stress_cash": 0.0}},
            "beta_tilt": {"factor_weights": {"beta": 0.5}},
            "mom2": {"factor_weights": {"momentum": 2.0}},
            "pead": {"factor_weights": {"pead": 1.0}}}


def with_change(cfg: dict, change: dict) -> dict:
    c = json.loads(json.dumps(cfg))
    for sect, kv in change.items():
        c[sect] = {**c.get(sect, {}), **kv}
    return c


def ic_test(inp, sv, cfg, start, end) -> dict:
    """Weekly cross-sectional rank IC over all liquid names: each factor's z-score
    (within cluster, as the composite uses it) at the signal date vs the return
    from the rebalance close to the next rebalance close. Also the top-minus-bottom
    quintile return per week. Weeks do not overlap, so the t-stats are honest."""
    close, volume = inp.close, inp.volume
    dates = close.index
    lo, hi = dates.searchsorted(start), dates.searchsorted(end, side="right")
    reb = [i for i in sim.rebalance_days(dates) if max(lo, sim.YEAR + 2) <= i < hi]
    sv_by = {d: g for d, g in sv.groupby("date")}
    names = [*factors.FACTORS, "composite"]
    ic, spread = {f: [] for f in names}, {f: [] for f in names}
    for n, (i, nxt) in enumerate(zip(reb[:-1], reb[1:])):
        sig = dates[i - 1]
        ft = factors.factor_table(close.iloc[:i].iloc[-sim.YEAR - 2:], volume.iloc[:i].iloc[-sim.YEAR - 2:],
                                  sv_by.get(sig, pd.DataFrame(columns=["ticker"])), inp.fund, inp.splits)
        pool = ft[factors.liquid(ft, **cfg["liquidity"])]
        g = clusters.at(inp.groups, sig)
        fwd = (close.iloc[nxt] / close.iloc[i] - 1).reindex(pool.index)
        for f in names:
            z = (combine.composite(pool, g, cfg["factor_weights"]) if f == "composite"
                 else combine.zscore(pool[f], g) if pool[f].notna().sum() >= 50 else None)
            if z is None:
                continue
            ic[f].append(stats.rank_ic(z, fwd))
            q = pd.qcut(z.rank(method="first"), 5, labels=False)
            spread[f].append(float(fwd[q == 4].mean() - fwd[q == 0].mean()))
        if n % 50 == 0:
            print(f"  ic week {n}/{len(reb)} ({dates[i].date()})", flush=True)
    res = {}
    for f in names:
        x, s = pd.Series(ic[f]).dropna(), pd.Series(spread[f]).dropna()
        if len(x) < 10:
            continue
        res[f"ic_{f}"] = {"weeks": len(x), "mean_ic": float(x.mean()), "ic_t_nw": stats.newey_west_t(x),
                          "hit_rate": float((x > 0).mean()), "q5_q1_ann": float(s.mean() * 52),
                          "q5_q1_t_nw": stats.newey_west_t(s)}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--only", help="comma list of: base,random,delay,cost2x,drop,ladder,markov,returns,ic,holdout")
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--candidate", default="pead",
                    help="holdout: comma list of VARIANTS to apply together (run once, see docs/AUDIT.md)")
    args = ap.parse_args()
    want = set((args.only or "base,random,delay,cost2x,drop").split(","))

    cfg = model.load_config()
    bt = cfg["backtest"]
    ds = Dataset()
    days = data.trading_days(ds)
    end = pd.Timestamp(days[-1]) - pd.Timedelta(days=30) - pd.DateOffset(months=bt["holdback_months"])
    start = pd.Timestamp(args.start or bt["start"])
    if "holdout" in want:  # the six held-back months, seen once by the pre-registered winner
        start = end + pd.Timedelta(days=1)
        end = pd.Timestamp(days[-1]) - pd.Timedelta(days=30)
        print(f"HOLDOUT {start.date()} -> {end.date()}, candidate {args.candidate}")
    inp = pipeline.load(ds, start.date(), end.date())
    dates = inp.close.index
    sig = [dates[i - k] for i in sim.rebalance_days(dates) for k in (1, 2)]
    sig += [dates[dates.searchsorted(start) - k] for k in (1, 2)]
    sv = data.load_state_vector(ds, data.window_start(start.date(), 10), end.date(), sig)
    spx_px = data.spx_close(ds)
    spx = spx_px.pct_change()
    wf = regime.weekly_table(spx_px.loc[:end], cfg.get("regime"))

    def run(name, strat, **kw):
        print(f"\n== {name}", flush=True)
        c = kw.pop("cfg", cfg)
        res = sim.run(inp.close, inp.volume, sv, strat, start, end, bt["cost_model"], bt["book_value"],
                      fund=inp.fund, splits=inp.splits, liquidity=c["liquidity"],
                      cost_cfg=kw.pop("cost_cfg", c.get("costs")),
                      no_trade_band=c["book"].get("no_trade_band"), **kw)
        m = sim.metrics(res["daily"])
        m.update(capm(res["daily"]["ret"], spx))
        daily[name] = res["daily"]["ret"]
        return m

    out, daily = {}, {}
    if ("base" in want or "returns" in want) and "holdout" not in want:
        out["base"] = run("base", model.strategy(inp.groups, cfg, wf))
    if "returns" in want:
        variants = dict(VARIANTS)
        variants["all4"] = {k: {kk: vv for v in variants.values() for kk, vv in v.get(k, {}).items()}
                            for k in ("regime", "factor_weights")}
        for name, change in variants.items():
            c = with_change(cfg, change)
            out[name] = run(name, model.strategy(inp.groups, c, wf), cfg=c)
        tried = ["base", *variants]
        srs = [daily[k].mean() / daily[k].std() for k in tried]
        for k in tried:
            out[k].update(stats.deflated_sharpe(daily[k], len(tried), srs))
            if k != "base":
                out[k].update(stats.paired_bootstrap(daily[k], daily["base"]))
                b = out["base"]
                out[k]["passes_1_2"] = bool(out[k]["ann_return"] - b["ann_return"] >= 0.01
                                             and out[k]["max_drawdown"] - b["max_drawdown"] <= 0.05)
    if "holdout" in want:
        change: dict = {}
        for v in args.candidate.split(","):
            for sect, kv in VARIANTS[v].items():
                change.setdefault(sect, {}).update(kv)
        out["base"] = run("base (v1.3)", model.strategy(inp.groups, cfg, wf))
        c = with_change(cfg, change)
        out[args.candidate] = run(args.candidate, model.strategy(inp.groups, c, wf), cfg=c)
        gap = out[args.candidate]["total_return"] - out["base"]["total_return"]
        print(f"\nholdout total-return gap {gap:+.2%}: " + ("GO (does not trail by more than 3 points)"
              if gap >= -0.03 else "NO-GO (trails v1.3 by more than 3 points)"))
    if "ic" in want:
        out.update(ic_test(inp, sv, cfg, start, end))
    if "markov" in want:  # stress method comparison, 25% cash dial in every row
        years_n = max((end - start).days / 365.25, 1e-9)
        for m in ("rule", "hmm_trend", "hmm"):
            c = json.loads(json.dumps(cfg))
            c["regime"] = {**c.get("regime", {}), "method": m, "stress_cash": c["regime"].get("stress_cash") or 0.25}
            wm = regime.weekly_table(spx_px.loc[:end], c["regime"])
            out[f"regime_{m}"] = run(f"regime {m}", model.strategy(inp.groups, c, wm), cfg=c)
            s = wm.loc[start:end, "stress"].astype(int)
            out[f"regime_{m}"]["switches_per_year"] = float(s.diff().abs().sum() / years_n)
            out[f"regime_{m}"]["weeks_flagged"] = float(s.mean())
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

    (ROOT / "artifacts").mkdir(exist_ok=True)
    if "ic" in want:
        ic = pd.DataFrame({k: v for k, v in out.items() if k.startswith("ic_")}).T
        pd.set_option("display.width", 200)
        print("\nweekly rank IC, all liquid names (|t| > 2 ~ unlikely to be luck)")
        print(ic.astype(float).round(4).to_string())
        out = {k: v for k, v in out.items() if not k.startswith("ic_")}
        (ROOT / "artifacts" / "audit_ic.json").write_text(json.dumps(ic.to_dict(orient="index"), indent=2))
        print("wrote artifacts/audit_ic.json")
    if not out:
        return
    extra = ["gap_ann", "gap_t_nw", "p_gap_le_0", "dsr", "passes_1_2"] if "returns" in want else []
    cols = (["switches_per_year", "weeks_flagged"] if "markov" in want else []) + extra + ["total_return", "ann_return", "ann_vol", "sharpe", "max_drawdown", "beta", "alpha_ann",
            "alpha_t", "turnover_per_year", "cost_total", "roll21_median", "roll21_p05"]
    table = pd.DataFrame(out).T.reindex(columns=cols)
    rnd = table[table.index.str.startswith("random")]
    if len(rnd) and "base" in table.index:
        better = int((rnd["total_return"] < table.loc["base", "total_return"]).sum())
        print(f"\nv1 beats {better} of {len(rnd)} random books on total return")
    pd.set_option("display.width", 200)
    print(table.astype(float).round(3).to_string())

    (ROOT / "artifacts" / "audit.json").write_text(json.dumps(out, indent=2, default=str))
    print("wrote artifacts/audit.json")


if __name__ == "__main__":
    main()
