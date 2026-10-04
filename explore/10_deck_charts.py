"""Pitch-deck charts in one visual style (same look as docs/img/growth.png).

    python explore/10_deck_charts.py

Reads artifacts/chart_daily_returns.csv (from explore/08_charts.py) and
config/book.json, reruns the model without the cash rule for the drawdown
comparison, and writes docs/img/deck_*.png. Numbers quoted in the factor,
tests and robustness charts are the audit results recorded in docs/AUDIT.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "docs" / "img"
INK, MUTED, GRID, BG = "#0F1B2D", "#5A6473", "#E4E1D8", "#FCFCFB"
TEAL, ORANGE, BLUE, GREY = "#0B8A6F", "#D9822B", "#3A6FB0", "#A7ADB5"
plt.rcParams.update({"font.size": 15, "axes.edgecolor": GRID, "axes.labelcolor": MUTED,
                     "xtick.color": MUTED, "ytick.color": MUTED, "figure.facecolor": BG,
                     "axes.facecolor": BG, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.spines.left": False})
SIZE = (13, 5.4)


def save(fig, name):
    fig.savefig(OUT / name, dpi=150)
    plt.close(fig)
    print("wrote", name)


def hbars(labels, values, colors, title_x, fmt="{:.1f}%", ref=None, ref_label=None, name="x.png"):
    fig, ax = plt.subplots(figsize=SIZE)
    y = np.arange(len(labels))[::-1]
    ax.barh(y, values, color=colors, height=0.62)
    for yi, v in zip(y, values):
        ax.text(v + max(values) * 0.01, yi, fmt.format(v), va="center", color=INK, fontsize=16)
    ax.set_yticks(y, labels, fontsize=16, color=INK)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, max(values) * 1.15)
    ax.grid(axis="x", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_xlabel(title_x)
    if ref is not None:
        ax.axvline(ref, color=INK, lw=1.2, ls="--")
        ax.text(ref, len(labels) - 0.35, f" {ref_label}", color=INK, fontsize=13, va="bottom")
    fig.tight_layout()
    save(fig, name)


rets = pd.read_csv(ROOT / "artifacts" / "chart_daily_returns.csv", index_col=0, parse_dates=True)

# 1. one month is mostly noise: spread of 21-day returns
r21 = (1 + rets["nabla"]).rolling(21).apply(np.prod, raw=True).dropna() - 1
fig, ax = plt.subplots(figsize=SIZE)
ax.hist(r21 * 100, bins=60, color=TEAL, alpha=0.9, edgecolor=BG, linewidth=0.6)
p5, med, p95 = np.percentile(r21 * 100, [5, 50, 95])
top = ax.get_ylim()[1]
ax.set_ylim(0, top * 1.18)
for v, lab, ha in [(p5, f"worst 1 in 20: {p5:.0f}% ", "right"), (med, f" typical: {med:+.1f}%", "left"),
                   (p95, f" best 1 in 20: {p95:+.0f}%", "left")]:
    ax.axvline(v, color=INK, lw=1.2, ls="--")
    ax.text(v, top * (1.12 if v != med else 1.03), lab, color=INK, fontsize=14, va="center", ha=ha)
ax.set_xlabel("Return over any 21 trading days (%), 2018 to 2026")
ax.set_yticks([])
ax.grid(axis="x", color=GRID, lw=0.8)
fig.tight_layout()
save(fig, "deck_noise.png")

# 2. which signals earn their place (drop-one-factor backtest, docs/AUDIT.md)
hbars(["All five signals", "Without momentum", "Without quality", "Without guidance",
       "Without value", "Without volatility premium"],
      [13.7, 7.3, 8.5, 11.7, 11.8, 19.2],
      [GREY, ORANGE, ORANGE, ORANGE, ORANGE, TEAL],
      "Return per year when one signal is removed (%)", ref=13.7, ref_label="all five", name="deck_factors.png")

# 3. the current book: 15 names, none above 10%
book = json.loads((ROOT / "config" / "book.json").read_text())
h = pd.Series({x["ticker"]: x["weight"] for x in book["holdings"]}).sort_values()
fig, ax = plt.subplots(figsize=SIZE)
ax.barh(h.index, h.values * 100, color=TEAL, height=0.62)
ax.axvline(10, color=INK, lw=1.2, ls="--")
ax.text(10, len(h) - 0.4, " 10% cap per stock", color=INK, fontsize=13, va="bottom")
ax.set_xlim(0, 11.5)
ax.tick_params(axis="y", length=0, labelsize=13)
ax.grid(axis="x", color=GRID, lw=0.8)
ax.set_axisbelow(True)
ax.set_xlabel(f"Weight in the book (%), as of {book['as_of']}")
fig.tight_layout()
save(fig, "deck_book.png")

# 4. cash rule: drawdown with and without it
from statevector import Dataset  # noqa: E402
from nabla import data, model, pipeline, regime, sim  # noqa: E402
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
wf = regime.weekly_flags(data.spx_close(ds).loc[:end])
nocash = json.loads(json.dumps(cfg))
nocash["regime"]["stress_cash"] = 0.0
res = sim.run(inp.close, inp.volume, sv, model.strategy(inp.groups, nocash, wf), start, end, bt["cost_model"],
              bt["book_value"], fund=inp.fund, splits=inp.splits, liquidity=cfg["liquidity"],
              cost_cfg=cfg.get("costs"), no_trade_band=cfg["book"].get("no_trade_band"))
both = pd.DataFrame({"with": rets["nabla"], "without": res["daily"]["ret"]}).dropna()
dd = (1 + both).cumprod()
dd = dd / dd.cummax() - 1
stress = wf["stress"].reindex(dd.index, method="ffill").fillna(False).astype(int)
fig, ax = plt.subplots(figsize=SIZE)
on = stress.diff().fillna(stress)
for a, b in zip(dd.index[on == 1], list(dd.index[on == -1]) + [dd.index[-1]] * 10):
    ax.axvspan(a, b, color="#EDE9DF", lw=0, zorder=0)
ax.plot(dd.index, dd["without"] * 100, color=GREY, lw=1.8)
ax.plot(dd.index, dd["with"] * 100, color=TEAL, lw=2.4)
ax.annotate(f"without the cash rule: worst {dd['without'].min():.0%}", (dd["without"].idxmin(), dd["without"].min() * 100),
            xytext=(40, -4), textcoords="offset points", color=MUTED, fontsize=14, va="center",
            arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
ax.annotate(f"with it: worst {dd['with'].min():.0%}", (dd["with"].idxmin(), dd["with"].min() * 100),
            xytext=(40, 4), textcoords="offset points", color=TEAL, fontsize=14, va="center", fontweight="bold",
            arrowprops=dict(arrowstyle="-", color=TEAL, lw=0.8))
ax.text(dd.index[0], 1.2, "shaded: weeks holding 25% cash", color=MUTED, fontsize=12, va="bottom")
ax.set_ylim(-38, 3)
ax.set_ylabel("Drop from peak (%)")
ax.grid(axis="y", color=GRID, lw=0.8)
fig.tight_layout()
save(fig, "deck_cash.png")
print("worst drawdowns:", dd.min().round(3).to_dict())

# 5. tests: our picks vs late data, random picks and the S&P
hbars(["nabla", "nabla with data 1 day late", "Random picks, same rules (median of 20)", "S&P 500"],
      [17.6, 13.7, 10.1, 12.4], [TEAL, GREY, GREY, BLUE],
      "Return per year, 2018 to 2026, after costs (%)", name="deck_tests.png")

# 6. robustness: every variant vs the S&P
hbars(["As shipped", "Trade at the next open", "Double trading costs", "Data one day late"],
      [17.6, 19.0, 16.6, 13.7], [TEAL, TEAL, TEAL, TEAL],
      "Return per year, 2018 to 2026, after costs (%)", ref=12.4, ref_label="S&P 500: 12.4%", name="deck_robust.png")
