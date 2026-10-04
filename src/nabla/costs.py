"""Trading costs, as a fraction of the book.

Each trade of weight change dw in a name pays

    half-spread  +  price impact
    |dw| * h_i   +  k * amihud_i * |dw| * V / 1e6 * |dw|

where h_i is 5, 10 or 20 bps by liquidity tier, amihud_i is the 21-day Amihud
illiquidity (|return| per $1M traded, as computed in factors.price_features),
V is the book value and k scales impact. Impact grows with the square of the
trade, so it only matters for big trades in thin names.

Tiers are terciles of 20-day dollar volume among the names that pass the
liquidity filter, so the most liquid third of what we can actually hold pays
5 bps and the least liquid third pays 20 bps. Names outside the filter (we only
ever sell them) pay the top tier.
"""
from __future__ import annotations

import pandas as pd

from . import factors

DEFAULTS = {"half_spread_bps": [5.0, 10.0, 20.0], "impact_k": 1.0, "max_adv_pct": 0.01}


def half_spread(ft: pd.DataFrame, liquidity: dict | None = None, cfg: dict | None = None) -> pd.Series:
    """Half-spread per name as a fraction (0.0005 = 5 bps)."""
    tiers = (cfg or DEFAULTS)["half_spread_bps"]
    ok = factors.liquid(ft, **(liquidity or {}))
    adv = ft["adv20"]
    lo, hi = adv[ok].quantile(1 / 3), adv[ok].quantile(2 / 3)
    bps = pd.Series(tiers[2], index=ft.index)
    bps[ok & (adv >= lo)] = tiers[1]
    bps[ok & (adv >= hi)] = tiers[0]
    return bps / 1e4


def impact_coef(ft: pd.DataFrame, book_value: float, cfg: dict | None = None) -> pd.Series:
    """Impact per unit of weight traded: cost of trading |dw| is coef * |dw| ** 2."""
    k = (cfg or DEFAULTS)["impact_k"]
    a = ft["amihud"].fillna(ft["amihud"].max())  # unknown liquidity counts as the worst seen
    return k * a * book_value / 1e6


def trade_cost(dw: pd.Series, ft: pd.DataFrame, book_value: float,
               liquidity: dict | None = None, cfg: dict | None = None) -> float:
    """Total cost of the weight changes dw, as a fraction of the book."""
    dw = dw[(dw.abs() > 0) & (dw.index != "CASHHOLDING")]  # cash trades free
    if dw.empty:
        return 0.0
    h = half_spread(ft, liquidity, cfg).reindex(dw.index).fillna((cfg or DEFAULTS)["half_spread_bps"][2] / 1e4)
    c = impact_coef(ft, book_value, cfg).reindex(dw.index)
    c = c.fillna(c.max() if c.notna().any() else 0.0)
    a = dw.abs()
    return float((a * h + c * a ** 2).sum())


def adv_cap(ft: pd.DataFrame, book_value: float, cfg: dict | None = None) -> pd.Series:
    """Largest weight per name so a position is at most 1% of 20-day dollar volume."""
    pct = (cfg or DEFAULTS)["max_adv_pct"]
    return (pct * ft["adv20"] / book_value).fillna(0.0)
