"""Simple walk-forward-style backtester: rebalance on a schedule using only
past information, charge transaction costs on turnover."""
import numpy as np
import pandas as pd


def backtest(prices: pd.DataFrame, weights_fn, rebalance_every: int = 21,
             cost_bps: float = 5.0, warmup: int = 252) -> pd.DataFrame:
    """`weights_fn(date) -> Series of weights` may use data up to and including
    `date` only; it is called with the prior trading day, so trades earn the
    next day's return (one-day lag).
    Returns DataFrame with columns: ret, equity, turnover."""
    rets = prices.pct_change()
    dates = prices.index
    w = pd.Series(0.0, index=prices.columns)
    out = []
    for i in range(warmup, len(dates)):
        turnover = 0.0
        if (i - warmup) % rebalance_every == 0:
            new_w = weights_fn(dates[i - 1]).reindex(prices.columns).fillna(0.0)
            turnover = float((new_w - w).abs().sum())
            w = new_w
        # weights built from info through dates[i-1] earn dates[i] return
        day_ret = float((w * rets.iloc[i].fillna(0.0)).sum()) - turnover * cost_bps / 1e4
        out.append((dates[i], day_ret, turnover))
    res = pd.DataFrame(out, columns=["date", "ret", "turnover"]).set_index("date")
    res["equity"] = (1 + res["ret"]).cumprod()
    return res


def stats(res: pd.DataFrame) -> dict:
    r = res["ret"]
    ann = 252
    eq = res["equity"]
    return {
        "total_return": float(eq.iloc[-1] - 1),
        "ann_vol": float(r.std() * np.sqrt(ann)),
        "sharpe": float(r.mean() / r.std() * np.sqrt(ann)) if r.std() > 0 else float("nan"),
        "max_drawdown": float((eq / eq.cummax() - 1).min()),
        "avg_turnover": float(res["turnover"].mean()),
    }
