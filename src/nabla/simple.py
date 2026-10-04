"""Two plain functions for the liquidity filter and trading costs.

Both take wide price and volume tables (index = dates, columns = tickers,
rows ending at the decision date) and need nothing else.

    from nabla.simple import liquid_tickers, trading_cost

    names = liquid_tickers(close, volume)                     # list of tickers
    cost = trading_cost({"AAPL": 0.10}, {"AAPL": 0.05, "MSFT": 0.08},
                        close, volume, book_value=1_000_000)  # fraction of the book
    cost_dollars = cost * 1_000_000
"""
from __future__ import annotations

from typing import Mapping

import pandas as pd

from . import costs, factors


def liquid_tickers(close: pd.DataFrame, volume: pd.DataFrame, min_adv: float = 50e6,
                   min_price: float = 5.0, drop_least_liquid: float = 0.10) -> list[str]:
    """Tickers we are allowed to hold on the last date in `close`.

    Keeps names with 20-day average dollar volume >= `min_adv`, price above
    `min_price` and a year of history, then drops the least liquid
    `drop_least_liquid` share of those by Amihud illiquidity.
    """
    ft = factors.price_features(close, volume)
    ok = factors.liquid(ft, min_adv, min_price, 1.0 - drop_least_liquid)
    return list(ft.index[ok])


def trading_cost(current: Mapping[str, float] | pd.Series, target: Mapping[str, float] | pd.Series,
                 close: pd.DataFrame, volume: pd.DataFrame, book_value: float = 1e6,
                 half_spread_bps: tuple[float, float, float] = (5.0, 10.0, 20.0),
                 impact_k: float = 1.0) -> float:
    """Cost of moving from `current` to `target` weights, as a fraction of the book.

    Half-spread of 5 / 10 / 20 bps by liquidity tier (most to least liquid third
    of tradable names) plus price impact that grows with trade size squared.
    Tickers missing from either side count as weight 0. Multiply by
    `book_value` for dollars.
    """
    cur, tgt = pd.Series(current, dtype=float), pd.Series(target, dtype=float)
    names = cur.index.union(tgt.index)
    dw = tgt.reindex(names, fill_value=0.0) - cur.reindex(names, fill_value=0.0)
    dw = dw.drop(labels=[n for n in dw.index if n.upper() in ("CASH", "CASHHOLDING")], errors="ignore")
    ft = factors.price_features(close, volume)
    cfg = {"half_spread_bps": list(half_spread_bps), "impact_k": impact_k, "max_adv_pct": 0.01}
    return costs.trade_cost(dw, ft, book_value, cfg=cfg)
