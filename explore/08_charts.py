"""Charts for the audit and the deck: growth of $1, drawdown, cluster exposure.

    python explore/08_charts.py

Runs the current model (config/model.json) and the equal-weight liquid universe
over the backtest window (config start to the cutoff minus the held-back
months, same as scripts/run_backtest.py), and writes PNGs to docs/img/.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from statevector import Dataset  # noqa: E402

from nabla import data, model, pipeline, regime, sim  # noqa: E402

OUT = ROOT / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
INK, MUTED, GRID, BG = "#0F1B2D", "#5A6473", "#E4E1D8", "#FCFCFB"
COL = {"nabla": "#0B8A6F", "Equal weight": "#D9822B", "S&P 500": "#3A6FB0"}
plt.rcParams.update({"font.size": 12, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "figure.facecolor": BG,
                     "axes.facecolor": BG, "axes.spines.top": False, "axes.spines.right": False})

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

runs = {}
for name, strat, band in [("nabla", model.strategy(inp.groups, cfg, wf), cfg["book"].get("no_trade_band")),
                          ("Equal weight", model.equal_weight_liquid(cfg), None)]:
    print(f"running {name}", flush=True)
    runs[name] = sim.run(inp.close, inp.volume, sv, strat, start, end, bt["cost_model"], bt["book_value"],
                         fund=inp.fund, splits=inp.splits, liquidity=cfg["liquidity"],
                         cost_cfg=cfg.get("costs"), no_trade_band=band)
idx = runs["nabla"]["daily"].index
rets = pd.DataFrame({k: v["daily"]["ret"] for k, v in runs.items()})
rets["S&P 500"] = spx_px.pct_change().reindex(idx).fillna(0.0)
rets.to_csv(ROOT / "artifacts" / "chart_daily_returns.csv")
growth = (1 + rets).cumprod()
dd = growth / growth.cummax() - 1
stress = wf["stress"].reindex(idx, method="ffill").fillna(False)


def shade(ax):
    on = stress.astype(int).diff().fillna(stress.astype(int))
    for a, b in zip(idx[on == 1], list(idx[on == -1]) + [idx[-1]] * 10):
        ax.axvspan(a, b, color="#EDE9DF", lw=0, zorder=0)


def label_end(ax, series_by_name, fmt):
    ys = sorted(((s.iloc[-1], n) for n, s in series_by_name.items()), reverse=True)
    last = None
    for y, n in ys:  # nudge labels apart
        yy = y if last is None else min(y, last - (ax.get_ylim()[1] - ax.get_ylim()[0]) * 0.06)
        ax.annotate(f"{n}  {fmt(y)}", (idx[-1], yy), xytext=(8, 0), textcoords="offset points",
                    va="center", color=INK, fontsize=12)
        last = yy


# 1. growth of $1
fig, ax = plt.subplots(figsize=(11, 5.2))
shade(ax)
for n in ["S&P 500", "Equal weight", "nabla"]:
    ax.plot(growth.index, growth[n], color=COL[n], lw=2.4 if n == "nabla" else 1.8, label=n)
ax.grid(axis="y", color=GRID, lw=0.8)
ax.set_ylabel("Growth of $1 (costs included)")
label_end(ax, {n: growth[n] for n in COL}, lambda y: f"${y:.2f}")
ax.set_title(f"nabla {cfg['version']} vs benchmarks, weekly replay {idx[0]:%b %Y} to {idx[-1]:%b %Y}",
             loc="left", color=INK, fontsize=14)
ax.text(0, -0.13, "Shaded: weeks the stress flag was on. Universe is today's listed stocks (survivorship).",
        transform=ax.transAxes, color=MUTED, fontsize=10)
ax.legend(frameon=False, loc="upper left")
fig.subplots_adjust(right=0.82, bottom=0.15)
fig.savefig(OUT / "growth.png", dpi=160)

# 2. drawdown
fig, ax = plt.subplots(figsize=(11, 4.2))
shade(ax)
for n in ["S&P 500", "Equal weight", "nabla"]:
    ax.plot(dd.index, dd[n] * 100, color=COL[n], lw=2.2 if n == "nabla" else 1.6, label=n)
ax.grid(axis="y", color=GRID, lw=0.8)
ax.set_ylabel("Drawdown from peak (%)")
ax.set_title("Drawdowns: worst " + ", ".join(f"{n} {dd[n].min():.0%}" for n in COL), loc="left",
             color=INK, fontsize=14)
ax.legend(frameon=False, loc="lower left")
fig.subplots_adjust(bottom=0.12)
fig.savefig(OUT / "drawdown.png", dpi=160)

# 3. cluster exposure (weekly book weights summed by return cluster)
books = runs["nabla"]["books"].set_index("date")
rows = []
for d, w in books["weights"].items():
    s = pd.Series(w, dtype=float)
    s = s[s.index != "CASHHOLDING"]
    rows.append(s.groupby(inp.groups.reindex(s.index).fillna("other")).sum().rename(d))
expo = pd.DataFrame(rows).fillna(0.0).sort_index()
mx = expo.drop(columns=["other"], errors="ignore").max(axis=1)
oth = expo["other"] if "other" in expo else pd.Series(0.0, index=expo.index)
fig, ax = plt.subplots(figsize=(11, 4.2))
ax.step(mx.index, mx * 100, where="post", color="#3A6FB0", lw=1.8)
ax.step(oth.index, oth * 100, where="post", color="#D9822B", lw=1.8)
ax.axhline(30, color=INK, lw=1, ls="--")
ax.annotate("30% group cap", (mx.index[0], 31), color=INK, fontsize=10)
ax.annotate("largest single cluster", (mx.index[-1], mx.iloc[-1] * 100), xytext=(8, 0),
            textcoords="offset points", va="center", color=INK)
ax.annotate("unclustered (uncapped)", (oth.index[-1], oth.iloc[-1] * 100), xytext=(8, 0),
            textcoords="offset points", va="center", color=INK)
ax.set_ylim(0, 60)
ax.grid(axis="y", color=GRID, lw=0.8)
ax.set_ylabel("Share of the book (%)")
ax.set_title("Concentration: the cap holds for clustered names; unclustered names reach "
             f"{oth.max():.0%}", loc="left", color=INK, fontsize=14)
fig.subplots_adjust(right=0.8, bottom=0.12)
fig.savefig(OUT / "clusters.png", dpi=160)
print("max single-cluster share per week: median %.0f%%, max %.0f%%" % (mx.median() * 100, mx.max() * 100))
print("'other' share: median %.0f%%, max %.0f%%" % (oth.median() * 100, oth.max() * 100))
print("wrote", sorted(p.name for p in OUT.glob("*.png")))
