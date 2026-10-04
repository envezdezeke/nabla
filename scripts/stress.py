"""Stress tests for the shipped model (v1.3): how does it behave when conditions change?

    python scripts/stress.py                         # every section
    python scripts/stress.py --only windows,book     # cheap sections first
    python scripts/stress.py --dev-only              # stop at the old holdback start

Nothing here selects or tunes anything: v1.3 stays as configured. The six
held-back months were spent on the PEAD go/no-go, so by default the tests run
2018 to the SDK cutoff (minus 30 days).

Sections (each runs full weekly backtests with plan costs unless noted):
  windows   one base run plus S&P 500 and the equal-weight liquid universe:
            crisis and rebound windows, behaviour by market regime (up/down
            months, volatility terciles, stress flag), rolling 21-day and
            12-month distributions, a block-bootstrap Monte Carlo of a 21-day
            judged window, the five deepest drawdowns
  book      the book held at the end of the data replayed through past crises,
            its beta, one-factor market shocks and cluster concentration (no backtest)
  timing    rebalance on the 2nd to 5th trading day of the week; every 2 and 4 weeks
  params    one-at-a-time perturbations (book size, bands, no-trade band, cash
            dial, sector cap, liquidity floor) and 10 random factor-weight draws
  costs     3x and 5x plan costs, the judges' flat 10 bps, next-open fills
  noise     Gaussian noise added to the composite (0.5x, 1x, 2x its spread, 3 seeds)
  universe  10 random 70% subsamples of the universe; remove the top 5 and top 10
            P&L names
Writes artifacts/stress.json. Factor tables are cached across runs, so every
run after the first costs only the book and trading loop.
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
sys.path.insert(0, str(ROOT / "scripts"))

from statevector import Dataset  # noqa: E402

from audit import capm, with_change  # noqa: E402
from nabla import clusters, combine, data, factors, model, pipeline, regime, sim  # noqa: E402

SECTIONS = ["windows", "book", "timing", "params", "costs", "noise", "universe"]
CRISES = {  # (start close, end close): peak-to-trough or the rebound after it
    "2018 Q4 sell-off": ("2018-09-20", "2018-12-24"),
    "Covid crash": ("2020-02-19", "2020-03-23"),
    "Covid rebound": ("2020-03-23", "2020-06-08"),
    "Vaccine rotation (momentum crash)": ("2020-11-06", "2020-12-04"),
    "2022 bear market": ("2022-01-03", "2022-10-12"),
    "2022-23 recovery": ("2022-10-12", "2023-07-31"),
    "SVB banking stress": ("2023-03-08", "2023-03-17"),
    "Aug 2024 yen unwind": ("2024-07-16", "2024-08-05"),
    "2025 tariff crash": ("2025-02-19", "2025-04-08"),
    "Tariff rebound": ("2025-04-08", "2025-06-30"),
}


def cache_factor_tables() -> None:
    """Memoize factors.factor_table: the same signal date and universe give the
    same table in every run here (sim.run looks it up through the module)."""
    raw, memo = factors.factor_table, {}

    def cached(close, volume, sv_day, fund=None, splits=None):
        key = (close.index[-1], len(close), hash(tuple(close.columns)), id(fund))
        if key not in memo:
            memo[key] = raw(close, volume, sv_day, fund, splits)
        return memo[key]
    factors.factor_table = cached


def window_ret(r: pd.Series, a, b) -> float:
    x = r.loc[(r.index > pd.Timestamp(a)) & (r.index <= pd.Timestamp(b))]
    return float((1 + x).prod() - 1) if len(x) else float("nan")


def max_dd(r: pd.Series) -> float:
    eq = (1 + r).cumprod()
    return float(abs((eq / eq.cummax() - 1).min())) if len(r) else float("nan")


def rolling(r: pd.Series, n: int) -> pd.Series:
    return np.exp(np.log1p(r).rolling(n).sum()).dropna() - 1


def dist(x: pd.Series) -> dict:
    q = x.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return {"p05": q[0.05], "p25": q[0.25], "median": q[0.5], "p75": q[0.75], "p95": q[0.95],
            "worst": float(x.min()), "best": float(x.max())}


def drawdowns(r: pd.Series, k: int = 5) -> list[dict]:
    eq = (1 + r).cumprod()
    dd = eq / eq.cummax() - 1
    out, i = [], 0
    while i < len(dd):
        if dd.iloc[i] < 0:
            j = i
            while j < len(dd) and dd.iloc[j] < 0:
                j += 1
            seg = dd.iloc[i:j]
            peak = dd.index[i - 1] if i > 0 else dd.index[i]
            out.append({"peak": str(peak.date()), "trough": str(seg.idxmin().date()),
                        "recovered": str(dd.index[j].date()) if j < len(dd) else "not yet",
                        "depth": float(-seg.min()), "days_to_trough": int(seg.index.get_loc(seg.idxmin()) + 1),
                        "days_underwater": int(j - i)})
            i = j
        i += 1
    return sorted(out, key=lambda d: -d["depth"])[:k]


def monte_carlo(port: pd.Series, mkt: pd.Series, horizon: int = 21, n: int = 20000,
                block: int = 5, seed: int = 0) -> dict:
    """Stationary block bootstrap of joint (portfolio, S&P) daily returns over a
    judged-length window."""
    x = pd.concat([port, mkt], axis=1, sort=True).dropna().to_numpy()
    rng = np.random.default_rng(seed)
    T = len(x)
    idx = np.empty((n, horizon), dtype=int)
    idx[:, 0] = rng.integers(T, size=n)
    jump = rng.random((n, horizon)) < 1.0 / block
    fresh = rng.integers(T, size=(n, horizon))
    for t in range(1, horizon):
        idx[:, t] = np.where(jump[:, t], fresh[:, t], (idx[:, t - 1] + 1) % T)
    p = np.prod(1 + x[idx, 0], axis=1) - 1
    m = np.prod(1 + x[idx, 1], axis=1) - 1
    return {"p05": float(np.quantile(p, .05)), "median": float(np.median(p)), "p95": float(np.quantile(p, .95)),
            "p_loss": float((p < 0).mean()), "p_beat_spx": float((p > m).mean()),
            "p_loss_over_5pct": float((p < -0.05).mean()), "p_trail_spx_by_3pct": float((p - m < -0.03).mean())}


def noisy_strategy(groups, cfg, wf, level: float, seed: int):
    """v1.3 with Gaussian noise added to the composite: how fast does the edge
    decay as the signal gets worse?"""
    raw = combine.composite

    def fn(ft, held, sig):
        def composite(pool, g, w):
            s = raw(pool, g, w)
            rng = np.random.default_rng([seed, pd.Timestamp(sig).toordinal()])
            return s + level * s.std() * pd.Series(rng.standard_normal(len(s)), index=s.index)
        combine.composite = composite
        try:
            return model.decide(ft, clusters.at(groups, sig), held, cfg, regime.flags_at(wf, sig))[0]
        finally:
            combine.composite = raw
    return fn


def contributions(books: pd.DataFrame, close: pd.DataFrame, end) -> pd.Series:
    """Approximate P&L per name: weight at each rebalance x the name's return to the next one."""
    total = pd.Series(0.0, index=close.columns)
    dates = list(books["date"]) + [pd.Timestamp(end)]
    for k, row in books.reset_index(drop=True).iterrows():
        a, b = row["date"], close.index[close.index <= dates[k + 1]][-1]
        w = pd.Series(row["weights"], dtype=float)
        w = w[w.index.isin(close.columns)]
        r = (close.loc[b, w.index] / close.loc[a, w.index] - 1).fillna(0.0)
        total[w.index] += w * r
    return total.sort_values(ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list of: " + ",".join(SECTIONS))
    ap.add_argument("--dev-only", action="store_true", help="end at the old holdback start")
    args = ap.parse_args()
    want = set((args.only or ",".join(SECTIONS)).split(","))
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)

    cfg = model.load_config()
    bt = cfg["backtest"]
    ds = Dataset()
    days = data.trading_days(ds)
    end = pd.Timestamp(days[-1]) - pd.Timedelta(days=30)
    if args.dev_only:
        end = end - pd.DateOffset(months=bt["holdback_months"])
    start = pd.Timestamp(bt["start"])
    print(f"stress tests {start.date()} -> {end.date()}, model {cfg.get('version')}")
    inp = pipeline.load(ds, start.date(), end.date())
    sv = data.load_state_vector(ds, data.window_start(start.date(), 10), end.date())  # every day: timing tests
    spx_px = data.spx_close(ds)
    spx = spx_px.pct_change()
    wf = regime.weekly_table(spx_px.loc[:end], cfg.get("regime"))
    cache_factor_tables()

    def run(name, strat=None, c=None, close=None, quiet=False, **kw):
        c = c or cfg
        if not quiet:
            print(f"== {name}", flush=True)
        res = sim.run(close if close is not None else inp.close, inp.volume if close is None else inp.volume[close.columns],
                      sv, strat or model.strategy(inp.groups, c, wf), start, end, kw.pop("cost_model", bt["cost_model"]),
                      bt["book_value"], fund=inp.fund, splits=inp.splits, liquidity=c["liquidity"],
                      cost_cfg=kw.pop("cost_cfg", c.get("costs")),
                      no_trade_band=kw.pop("no_trade_band", c["book"].get("no_trade_band")), **kw)
        m = sim.metrics(res["daily"])
        m.update(capm(res["daily"]["ret"], spx))
        return res, m

    def show(title, rows, cols=("ann_return", "sharpe", "max_drawdown", "beta", "alpha_ann", "turnover_per_year",
                                "cost_total")):
        t = pd.DataFrame(rows).T
        print(f"\n### {title}")
        print(t.reindex(columns=[c for c in cols if c in t.columns] or t.columns).astype(float).round(3).to_string())
        return t

    out: dict = {"window": [str(start.date()), str(end.date())], "version": cfg.get("version")}
    base_res, base = run("base v1.3")
    port = base_res["daily"]["ret"]
    mkt = spx.reindex(port.index).fillna(0.0)
    spx_m = {**sim.metrics(mkt.to_frame("ret").assign(turnover=0.0, cost=0.0))}
    out["base"] = base
    ref = {"v1.3": base, "S&P 500": spx_m}

    if "windows" in want:
        ew_res, ew = run("equal-weight liquid", model.equal_weight_liquid(cfg), no_trade_band=None)
        ewr = ew_res["daily"]["ret"]
        ref["EW liquid"] = ew
        show("full period", ref)
        rows = {}
        for k, (a, b) in CRISES.items():
            if pd.Timestamp(b) > end or pd.Timestamp(a) < port.index[0]:
                continue
            seg = port.loc[(port.index > pd.Timestamp(a)) & (port.index <= pd.Timestamp(b))]
            rows[k] = {"v1.3": window_ret(port, a, b), "S&P 500": window_ret(mkt, a, b),
                       "EW liquid": window_ret(ewr, a, b), "v1.3 max DD": max_dd(seg)}
            rows[k]["vs S&P"] = rows[k]["v1.3"] - rows[k]["S&P 500"]
        t = show("crisis and rebound windows (total return over the window)", rows,
                 ("v1.3", "S&P 500", "EW liquid", "vs S&P", "v1.3 max DD"))
        out["crises"] = t.to_dict(orient="index")

        mon = pd.DataFrame({"p": (1 + port).resample("ME").prod() - 1, "m": (1 + mkt).resample("ME").prod() - 1})
        up, dn = mon[mon["m"] > 0], mon[mon["m"] <= 0]
        vol = mkt.rolling(21).std().shift(1) * np.sqrt(252)
        terc = pd.qcut(vol.dropna(), 3, labels=["calm", "normal", "high vol"])
        stress = wf["stress"].astype(float).reindex(port.index, method="ffill").shift(1).fillna(0) > 0
        reg = {"up months": {"months": len(up), "v1.3 avg": up["p"].mean(), "S&P avg": up["m"].mean(),
                             "capture": up["p"].mean() / up["m"].mean()},
               "down months": {"months": len(dn), "v1.3 avg": dn["p"].mean(), "S&P avg": dn["m"].mean(),
                               "capture": dn["p"].mean() / dn["m"].mean()}}
        for lab in ["calm", "normal", "high vol"]:
            d = terc.index[terc == lab]
            reg[f"{lab} days"] = {"days": len(d), "v1.3 ann": port[d].mean() * 252, "S&P ann": mkt[d].mean() * 252,
                                  "beta": capm(port[d], mkt[d])["beta"]}
        for lab, mask in {"stress flag on": stress, "stress flag off": ~stress}.items():
            d = port.index[mask]
            reg[lab] = {"days": len(d), "v1.3 ann": port[d].mean() * 252, "S&P ann": mkt[d].mean() * 252,
                        "beta": capm(port[d], mkt[d])["beta"]}
        t = pd.DataFrame(reg).T
        print("\n### up and down S&P months (average monthly return; capture = v1.3 / S&P)")
        print(t.loc[["up months", "down months"], ["months", "v1.3 avg", "S&P avg", "capture"]].astype(float).round(3).to_string())
        print("\n### by S&P volatility tercile (prior 21 days) and stress flag (daily mean x 252)")
        print(t.drop(["up months", "down months"])[["days", "v1.3 ann", "S&P ann", "beta"]].astype(float).round(3).to_string())
        out["regimes"] = t.to_dict(orient="index")

        r21, m21 = rolling(port, 21), rolling(mkt, 21)
        r252, m252 = rolling(port, 252), rolling(mkt, 252)
        ex21, ex252 = (r21 - m21).dropna(), (r252 - m252).dropna()
        rl = {"v1.3 21d": dist(r21), "v1.3 - S&P 21d": dist(ex21), "v1.3 12m": dist(r252), "v1.3 - S&P 12m": dist(ex252)}
        t = pd.DataFrame(rl).T
        print("\n### rolling windows (every start date)")
        print(t.astype(float).round(3).to_string())
        odds = {"21d: P(loss)": float((r21 < 0).mean()), "21d: P(beat S&P)": float((ex21 > 0).mean()),
                "21d: P(trail S&P by >3%)": float((ex21 < -0.03).mean()),
                "12m: P(loss)": float((r252 < 0).mean()), "12m: P(beat S&P)": float((ex252 > 0).mean())}
        print(pd.Series(odds).round(3).to_string())
        mc = monte_carlo(port, mkt)
        print("\n### Monte Carlo of one 21-day judged window (block bootstrap, 20,000 paths)")
        print(pd.Series(mc).round(3).to_string())
        dds = drawdowns(port)
        print("\n### five deepest drawdowns")
        print(pd.DataFrame(dds).to_string(index=False))
        out.update({"rolling": t.to_dict(orient="index"), "rolling_odds": odds, "monte_carlo_21d": mc,
                    "drawdowns": dds})

    if "book" in want:
        w = base_res["final_weights"]
        w = w[w > 0]
        cash = 1 - float(w.sum())
        close = inp.close
        rets = close.pct_change(fill_method=None)
        last = close.index[-1]
        hist = rets.loc[:last].iloc[-252:]
        m = mkt.reindex(hist.index)
        betas = hist[w.index].apply(lambda s: capm(s, m)["beta"])
        book_beta = float((w * betas).sum())
        g = clusters.at(inp.groups, last).reindex(w.index).fillna("other")
        print(f"\n### book at {last.date()}: {len(w)} names, cash {cash:.1%}, beta vs S&P {book_beta:.2f} "
              f"(252-day, per name)")
        print(pd.DataFrame({"weight": w, "beta": betas, "cluster": g}).sort_values("weight", ascending=False)
              .round(3).to_string())
        print("cluster weights:", w.groupby(g).sum().sort_values(ascending=False).round(3).to_dict())
        scen = {}
        for k, (a, b) in CRISES.items():
            a_, b_ = close.index[close.index <= pd.Timestamp(a)], close.index[close.index <= pd.Timestamp(b)]
            if not len(a_) or not len(b_):
                continue
            r = close.loc[b_[-1], w.index] / close.loc[a_[-1], w.index] - 1
            have = r.notna()
            scen[k] = {"book (names with history)": float((w[have] * r[have]).sum() / w[have].sum() * w.sum()),
                       "S&P 500": window_ret(mkt, a, b), "weight covered": float(w[have].sum() / w.sum())}
        for shock in (-0.05, -0.10, -0.20):
            scen[f"S&P {shock:.0%} shock (beta x shock)"] = {"book (names with history)": book_beta * shock,
                                                            "S&P 500": shock, "weight covered": 1.0}
        t = pd.DataFrame(scen).T
        print("\n### today's book replayed through past windows (no rebalancing, cash earns 0)")
        print(t.astype(float).round(3).to_string())
        out["book"] = {"date": str(last.date()), "weights": w.round(4).to_dict(), "cash": cash, "beta": book_beta,
                       "clusters": w.groupby(g).sum().to_dict(), "scenarios": t.to_dict(orient="index")}

    if "timing" in want:
        rows = {"weekly, day 1 (v1.3)": base}
        for k in range(1, 5):
            rows[f"weekly, day {k + 1}"] = run(f"rebalance day {k + 1}", rebal_offset=k)[1]
        for e in (2, 4):
            rows[f"every {e} weeks"] = run(f"every {e} weeks", rebal_every=e)[1]
        out["timing"] = show("rebalance timing", rows).to_dict(orient="index")

    if "params" in want:
        b = cfg["book"]
        changes = {"n 10 (exit 20)": {"book": {"n": 10, "exit_rank": 20}},
                   "n 12 (exit 24)": {"book": {"n": 12, "exit_rank": 24}},
                   "n 20 (exit 40)": {"book": {"n": 20, "exit_rank": 40}},
                   "n 25 (exit 50)": {"book": {"n": 25, "exit_rank": 50}},
                   "exit rank 20": {"book": {"exit_rank": 20}}, "exit rank 45": {"book": {"exit_rank": 45}},
                   "no-trade band 0": {"book": {"no_trade_band": 0.0}},
                   "no-trade band 4%": {"book": {"no_trade_band": 0.04}},
                   "stress cash 15%": {"regime": {"stress_cash": 0.15}},
                   "stress cash 40%": {"regime": {"stress_cash": 0.40}},
                   "sector cap 20%": {"book": {"sector_cap": 0.2}}, "no sector cap": {"book": {"sector_cap": 1.0}},
                   "min ADV $25M": {"liquidity": {"min_adv": 25e6}}, "min ADV $100M": {"liquidity": {"min_adv": 100e6}}}
        rng = np.random.default_rng(7)
        active = [f for f, v in cfg["factor_weights"].items() if v > 0]
        for d in range(10):
            fw = {f: float(np.exp(rng.normal(0, 0.4))) for f in active}
            changes[f"weights draw {d}: " + " ".join(f"{f[:4]}{v:.1f}" for f, v in fw.items())] = {"factor_weights": fw}
        rows = {f"v1.3 (n {b['n']}, exit {b['exit_rank']})": base}
        for name, ch in changes.items():
            rows[name] = run(name, c=with_change(cfg, ch))[1]
        t = show("parameter perturbations (one change at a time; not a search, nothing here ships)", rows)
        beat = int((t["ann_return"].iloc[1:] > spx_m["ann_return"]).sum())
        print(f"{beat} of {len(rows) - 1} perturbations beat the S&P 500 ({spx_m['ann_return']:.1%}/yr); "
              f"range {t['ann_return'].min():.1%} to {t['ann_return'].max():.1%}")
        out["params"] = t.to_dict(orient="index")

    if "costs" in want:
        rows = {"plan costs (v1.3)": base}
        for x in (3, 5):
            cc = dict(cfg["costs"])
            cc["half_spread_bps"] = [x * v for v in cc["half_spread_bps"]]
            cc["impact_k"] = x * cc["impact_k"]
            rows[f"{x}x plan costs"] = run(f"{x}x costs", cost_cfg=cc)[1]
        rows["judges' flat 10 bps"] = run("flat 10 bps", cost_model="flat")[1]
        raw_px = data.load_prices(ds, inp.close.index[0].date(), end.date(), list(inp.close.columns))
        raw_close = data.to_wide(raw_px, "close").reindex_like(inp.close)
        opens = data.to_wide(data.load_opens(ds, inp.close.index[0].date(), end.date()), "open")
        opens = data.adjust_like(opens.reindex_like(inp.close), raw_close, inp.close)
        rows["next-open fills"] = run("next-open fills", open_=opens)[1]
        t = show("trading costs and fills", rows)
        per_x = (base["ann_return"] - rows["5x plan costs"]["ann_return"]) / 4
        if per_x > 0:
            lead = base["ann_return"] - spx_m["ann_return"]
            vs_spx = (f"stops beating the S&P 500 at about {1 + lead / per_x:.1f}x plan costs" if lead > 0
                      else "already trails the S&P 500 at plan costs")
            print(f"each extra 1x of plan costs takes ~{per_x:.2%}/yr; {vs_spx}; "
                  f"return reaches 0 at about {1 + base['ann_return'] / per_x:.1f}x")
        out["costs"] = t.to_dict(orient="index")

    if "noise" in want:
        rows = {"no noise (v1.3)": base}
        for lvl in (0.5, 1.0, 2.0):
            for s in range(3):
                rows[f"noise {lvl}x, seed {s}"] = run(f"noise {lvl} seed {s}",
                                                      noisy_strategy(inp.groups, cfg, wf, lvl, s))[1]
        t = show("signal noise (noise sd as a multiple of the composite's cross-sectional sd)", rows)
        out["noise"] = t.to_dict(orient="index")

    if "universe" in want:
        rows = {"full universe (v1.3)": base}
        cols = inp.close.columns
        for s in range(10):
            keep = cols[np.random.default_rng(100 + s).random(len(cols)) < 0.7]
            rows[f"70% subsample {s}"] = run(f"subsample {s}", close=inp.close[keep])[1]
        con = contributions(base_res["books"], inp.close, end)
        print("\ntop 10 P&L names (sum of weight x period return):", con.head(10).round(3).to_dict())
        print(f"top 10 names = {con.head(10).sum() / con.sum():.0%} of summed P&L")
        for k in (5, 10):
            keep = cols.difference(con.head(k).index)
            rows[f"without top {k} names"] = run(f"without top {k}", close=inp.close[keep])[1]
        t = show("universe: random subsamples and removing the biggest winners", rows)
        sub = t[t.index.str.startswith("70%")]
        print(f"subsamples: median {sub['ann_return'].median():.1%}/yr, {int((sub['ann_return'] > spx_m['ann_return']).sum())}"
              f" of {len(sub)} beat the S&P 500")
        out["universe"] = {"runs": t.to_dict(orient="index"), "top_names": con.head(10).to_dict()}

    (ROOT / "artifacts").mkdir(exist_ok=True)
    (ROOT / "artifacts" / "stress.json").write_text(json.dumps(out, indent=2, default=str))
    print("\nwrote artifacts/stress.json")


if __name__ == "__main__":
    main()
