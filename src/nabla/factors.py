"""The five v1 factors for one decision date. Higher = more attractive.

Inputs are split-adjusted wide frames (index=date, columns=ticker) holding
data through the decision date only, plus that date's state-vector rows.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import fundamentals

MONTH, YEAR = 21, 252
FACTORS = ["momentum", "guidance_velocity", "quality", "value", "vol_premium"]


def price_features(close: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker features from the last year of prices (rows end at the decision date)."""
    rets = close.pct_change(fill_method=None)
    dv = close * volume
    last = close.iloc[-1]
    out = pd.DataFrame({
        "price": last,
        # 12-1 momentum: t-12m to t-1m, skipping the reversal-prone last month
        "momentum": close.iloc[-1 - MONTH] / close.iloc[-1 - YEAR] - 1 if len(close) > YEAR else np.nan,
        "rv21": rets.iloc[-MONTH:].std() * np.sqrt(YEAR),
        "adv20": dv.iloc[-20:].mean(),
        # Amihud x 1e6: mean |return| per dollar traded
        "amihud": (rets.abs() / dv.replace(0, np.nan)).iloc[-MONTH:].mean() * 1e6,
    })
    return out


def factor_table(close: pd.DataFrame, volume: pd.DataFrame, sv_day: pd.DataFrame,
                 fund: pd.DataFrame | None = None, splits: pd.DataFrame | None = None) -> pd.DataFrame:
    """All v1 factors plus the inputs the book needs (liquidity, earnings clock).

    `fund` is `fundamentals.prepare(...)` output; quality and value then come from
    filings knowable by 16:00 on the last date in `close`. Without it, quality is
    neutral and value falls back to the state vector's FCF gap."""
    ft = price_features(close, volume)
    sv = sv_day.drop_duplicates("ticker").set_index("ticker").reindex(ft.index)

    def col(name: str) -> pd.Series:
        return sv[name].astype(float) if name in sv else pd.Series(np.nan, index=ft.index)

    ft["guidance_velocity"] = col("guidance_range_velocity")
    # fallback value: log_fv_gap = log(spot / FCF fair value); cheaper -> higher
    ft["value"] = -col("log_fv_gap")
    ft["quality"] = np.nan
    # volatility premium: options priced above delivered vol predict lower returns.
    # Unit differences in atm_iv only shift the log by a constant, so ranks are unaffected.
    ft["vol_premium"] = -np.log(col("atm_iv") / ft["rv21"])
    ft["days_to_next_report"] = col("days_to_next_report")
    ft.attrs["fund_notes"] = {"quality_def": "unavailable", "value_def": "fcf_gap_state_vector"}
    if fund is not None and len(fund):
        cutoff = pd.Timestamp(close.index[-1]).normalize() + pd.Timedelta(hours=16)
        qv, notes = fundamentals.quality_value(fund, ft["price"], cutoff, splits)
        ft["quality"] = qv["quality"]
        if notes["value_def"] != "unavailable":
            ft["value"] = qv["value"]
        else:
            notes["value_def"] = "fcf_gap_state_vector"
        ft.attrs["fund_notes"] = notes
    return ft.replace([np.inf, -np.inf], np.nan)


def liquid(ft: pd.DataFrame, min_adv: float = 50e6, min_price: float = 5.0,
           amihud_drop_pct: float = 0.90) -> pd.Series:
    """Liquidity filter: ADV20 > $50M, price > $5, drop the most illiquid Amihud decile."""
    ok = (ft["adv20"] > min_adv) & (ft["price"] > min_price) & ft["momentum"].notna()
    cut = ft.loc[ok, "amihud"].quantile(amihud_drop_pct)
    return ok & ~(ft["amihud"] > cut)
