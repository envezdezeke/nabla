"""Score a replay file the way the judges' format implies: trade at the next open.

    python scripts/score_replay.py [artifacts/replay.jsonl]

For each "rebalance" record the book trades to target_holdings at the open of
execution_time; between trades holdings drift with prices. Each day's return is
split at the open on trade days (overnight close->open on the old book, then
open->close on the new one). Costs: the judges' flat schedule (10 bps per dollar
traded, CASHHOLDING free) and the plan's model (half-spread by liquidity tier +
Amihud impact). Prices are split-adjusted the same way as the model's. Compared
with SPX and with an equal-weight book of the same tickers held all window.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statevector import Dataset  # noqa: E402

from nabla import data, factors  # noqa: E402
from nabla.costs import trade_cost  # noqa: E402

CASH = "CASHHOLDING"


def main(path: Path) -> None:
    recs = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    trades = [r for r in recs if r["action"] == "rebalance"]
    if not trades:
        sys.exit("no rebalance records in the file")
    ds = Dataset()
    exec_days = [pd.Timestamp(r["execution_time"][:10]) for r in trades]
    tickers = sorted({h["ticker"] for r in trades for h in r["target_holdings"]} - {CASH})
    start, end = exec_days[0] - pd.Timedelta(days=400), pd.Timestamp(data.last_trading_day(ds))
    px = (ds.get("stocks_daily", start=str(start.date()), end=str(end.date()), limit=data.BIG, lazy=True)
          .filter(pl.col("ticker").is_in(tickers)).select(["ticker", "date", "open", "close", "volume"])
          .collect().to_pandas())
    px["date"] = pd.to_datetime(px["date"])
    close, opn, vol = (px.pivot_table(index="date", columns="ticker", values=c) for c in ("close", "open", "volume"))
    ratio = opn / close  # adjust opens by the same split factors as closes
    close, vol, _ = data.split_adjust(close, vol, data.load_splits(ds))
    opn = ratio * close
    days = close.index[close.index >= exec_days[0]]
    if exec_days[0] not in close.index:
        print(f"note: first execution day {exec_days[0].date()} is past the data; nothing to score")
        return
    targets = {d: pd.Series({h["ticker"]: h["weight"] for h in r["target_holdings"]}) for d, r in zip(exec_days, trades)}

    w = pd.Series(dtype=float)  # weights at the previous close, cash included as the residual
    rows, cost_flat, cost_plan, turnover = [], 0.0, 0.0, 0.0
    for t in days:
        i = close.index.get_loc(t)
        prev_c = close.iloc[i - 1]
        r_day = 0.0
        if t in targets:
            stock = w.drop(CASH, errors="ignore")
            r_on = float((stock * (opn.loc[t, stock.index] / prev_c[stock.index] - 1).fillna(0)).sum())
            w_open = stock * (opn.loc[t, stock.index] / prev_c[stock.index]).fillna(1) / (1 + r_on)
            tgt = targets[t].drop(CASH, errors="ignore")
            names = tgt.index.union(w_open.index)
            dw = tgt.reindex(names, fill_value=0) - w_open.reindex(names, fill_value=0)
            ft = factors.price_features(close.iloc[: i], vol.iloc[: i])
            c_flat = float(dw.abs().sum()) * 10 / 1e4
            c_plan = trade_cost(dw, ft, 1e6 * (1 + sum(x[1] for x in rows)), None, None)
            cost_flat += c_flat
            cost_plan += c_plan
            turnover += float(dw.abs().sum())
            r_in = float((tgt * (close.loc[t, tgt.index] / opn.loc[t, tgt.index] - 1).fillna(0)).sum())
            r_day = (1 + r_on) * (1 + r_in) - 1
            w = tgt * (close.loc[t, tgt.index] / opn.loc[t, tgt.index]).fillna(1) / (1 + r_in)
            rows.append((t, r_day, c_flat, c_plan))
        else:
            stock = w.drop(CASH, errors="ignore")
            rr = (close.loc[t, stock.index] / prev_c[stock.index] - 1).fillna(0)
            r_day = float((stock * rr).sum())
            w = stock * (1 + rr) / (1 + r_day)
            rows.append((t, r_day, 0.0, 0.0))
    df = pd.DataFrame(rows, columns=["date", "gross", "cost_flat", "cost_plan"]).set_index("date")
    gross = (1 + df["gross"]).prod() - 1
    net_flat = (1 + df["gross"] - df["cost_flat"]).prod() - 1
    net_plan = (1 + df["gross"] - df["cost_plan"]).prod() - 1
    spx = data.spx_close(ds).dropna()
    a, b = close.index[close.index.get_loc(df.index[0]) - 1], df.index[-1]
    spx_ret = float(spx.asof(b) / spx.asof(a) - 1) if len(spx) and spx.index[0] <= a else float("nan")
    spx_note = "" if len(spx) and spx.index[-1] >= b else f"  (index data ends {spx.index[-1].date() if len(spx) else 'n/a'})"
    first = targets[exec_days[0]].drop(CASH, errors="ignore").index
    ew = float((close.loc[df.index[-1], first] / opn.loc[df.index[0], first] - 1).mean())
    eq = (1 + df["gross"] - df["cost_plan"]).cumprod()
    print(f"window: {df.index[0].date()} open -> {df.index[-1].date()} close  ({len(df)} trading days, {len(trades)} rebalances)")
    print(f"  gross return                 {gross:+.2%}")
    print(f"  net, judges' flat 10 bps     {net_flat:+.2%}   (cost {cost_flat:.2%}, turnover {turnover:.2f})")
    print(f"  net, plan cost model         {net_plan:+.2%}   (cost {cost_plan:.2%})")
    print(f"  max drawdown (net, plan)     {float((eq / eq.cummax() - 1).min()):.2%}")
    print(f"  S&P 500 over the same days   {spx_ret:+.2%}{spx_note}")
    print(f"  first book held, equal wt    {ew:+.2%}   (no rebalancing, no costs)")
    print("\n  weekly:")
    for d in exec_days:
        wk = df.loc[d: d + pd.Timedelta(days=6)]
        print(f"    week of {d.date()}: {float((1 + wk['gross'] - wk['cost_plan']).prod() - 1):+.2%}")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "replay.jsonl")
