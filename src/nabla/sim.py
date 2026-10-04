"""Weekly backtest that runs the live decision loop.

Conventions match the judges' engine (statevector.backtest): close-to-close
returns, missing prints earn 0, weights drift between rebalances, a rebalance
resets weights at that day's close and pays costs the same day. Signals for a
rebalance on day t use data through day t-1 only.
"""
from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from . import costs, factors

YEAR = 252


def rebalance_days(dates: pd.DatetimeIndex) -> list[int]:
    """Index of the first trading day of each ISO week (the engine's weekly rule)."""
    wk = [d.isocalendar()[:2] for d in dates]
    return [i for i in range(1, len(dates)) if wk[i] != wk[i - 1]]


def trade_cost(dw: pd.Series, ft: pd.DataFrame, book_value: float, model: str,
               flat_bps: float = 10.0, liquidity: dict | None = None, cost_cfg: dict | None = None) -> float:
    """Cost as a fraction of the book for weight changes dw.

    plan: costs.trade_cost (half-spread 5/10/20 bps by liquidity tier + Amihud impact).
    flat: the judges' schedule, flat_bps on every dollar traded.
    """
    if model == "flat":
        dw = dw[dw.abs() > 0]
        return float(dw.abs().sum() * flat_bps / 1e4)
    return costs.trade_cost(dw, ft, book_value, liquidity, cost_cfg)


def run(close: pd.DataFrame, volume: pd.DataFrame, sv: pd.DataFrame,
        strategy: Callable, start, end, cost_model: str = "plan",
        book_value: float = 1e6, fund: pd.DataFrame | None = None,
        splits: pd.DataFrame | None = None, liquidity: dict | None = None,
        cost_cfg: dict | None = None, signal_lag: int = 1,
        no_trade_band: float | None = None) -> dict:
    """strategy(ft, held: list[str], signal_date) -> target weights (Series, sums to <= 1).

    signal_lag: decisions on day i use data through day i - signal_lag (1 = the
    prior close; 2 is the one-day-delay leak test).
    no_trade_band: skip weight changes smaller than this (book.no_trade)."""
    from .book import no_trade
    rets = close.pct_change(fill_method=None).fillna(0.0)
    dates = close.index
    lo, hi = dates.searchsorted(pd.Timestamp(start)), dates.searchsorted(pd.Timestamp(end), side="right")
    lo = max(lo, YEAR + signal_lag + 1)
    rebal = set(i for i in rebalance_days(dates) if lo <= i < hi)
    sv_by_date = {d: g for d, g in sv.groupby("date")}

    w = pd.Series(dtype=float)
    out, books = [], []
    value = 1.0
    for i in range(lo, hi):
        r = float((w * rets.iloc[i].reindex(w.index).fillna(0.0)).sum()) if len(w) else 0.0
        if len(w):  # drift; weights stay fractions of the whole book, cash included
            w = w * (1 + rets.iloc[i].reindex(w.index).fillna(0.0)) / (1 + r)
        cost, turn = 0.0, 0.0
        if i in rebal or (i == lo):
            j = i - signal_lag + 1  # rows [0, j) are known at the decision
            sig = dates[j - 1]
            ft = factors.factor_table(close.iloc[:j].iloc[-YEAR - 2:], volume.iloc[:j].iloc[-YEAR - 2:],
                                      sv_by_date.get(sig, pd.DataFrame(columns=["ticker"])),
                                      fund, splits)
            target = strategy(ft, list(w.index[w > 0]), sig)
            if no_trade_band:
                target = no_trade(w, target, no_trade_band)
            dw = target.reindex(target.index.union(w.index), fill_value=0.0) - \
                w.reindex(target.index.union(w.index), fill_value=0.0)
            cost = trade_cost(dw, ft, book_value * value, cost_model, liquidity=liquidity, cost_cfg=cost_cfg)
            turn = float(dw.abs().sum())
            w = target[target > 0]
            if len(books) % 50 == 0:
                print(f"  rebalance {len(books)}/{len(rebal)} ({dates[i].date()})", flush=True)
            books.append({"date": dates[i], "signal_date": sig, "names": len(w),
                          "turnover": turn, "cost": cost})
        port = r - cost
        value *= 1 + port
        out.append((dates[i], port, r, turn, cost))
    if len(w):  # liquidate at the end, as the judges' engine does
        last = out[-1]
        exit_cost = trade_cost(-w, ft, book_value * value, cost_model, liquidity=liquidity, cost_cfg=cost_cfg)
        out[-1] = (last[0], last[1] - exit_cost, last[2], last[3] + float(w.sum()), last[4] + exit_cost)
    daily = pd.DataFrame(out, columns=["date", "ret", "gross", "turnover", "cost"]).set_index("date")
    return {"daily": daily, "books": pd.DataFrame(books), "final_weights": w}


def metrics(daily: pd.DataFrame) -> dict:
    r = daily["ret"]
    n = len(r)
    eq = (1 + r).cumprod()
    total = float(eq.iloc[-1] - 1)
    roll = (1 + r).rolling(21).apply(np.prod, raw=True).dropna() - 1
    sd = r.std()
    return {
        "n_days": n,
        "total_return": total,
        "ann_return": float((1 + total) ** (YEAR / n) - 1),
        "ann_vol": float(sd * np.sqrt(YEAR)),
        "sharpe": float(r.mean() / sd * np.sqrt(YEAR)) if sd > 0 else 0.0,
        "max_drawdown": float(abs((eq / eq.cummax() - 1).min())),
        "turnover_per_year": float(daily["turnover"].sum() * YEAR / n),
        "cost_total": float(daily["cost"].sum()),
        "roll21_median": float(roll.median()) if len(roll) else None,
        "roll21_p05": float(roll.quantile(0.05)) if len(roll) else None,
        "roll21_p95": float(roll.quantile(0.95)) if len(roll) else None,
        "roll21_worst": float(roll.min()) if len(roll) else None,
    }


def period_returns(daily: pd.DataFrame, periods: dict[str, tuple[str, str]]) -> dict:
    out = {}
    for name, (a, b) in periods.items():
        r = daily.loc[a:b, "ret"]
        out[name] = float((1 + r).prod() - 1) if len(r) else None
    return out
