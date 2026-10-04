"""Stress and panic flags from the plan (Step 1), as pure functions of data.

    stress: S&P 500 below its 200-day average AND (21-day realized volatility
            OR funding stress above its 80th percentile of all history so far)
    panic:  S&P 500 down over 12 months AND 21-day volatility above its 80th percentile

Percentiles use expanding history only (nothing after the date). A flag
switches on when its condition is true at a weekly check and switches off only
after two straight weekly checks with the condition false (hysteresis). The
whole weekly history is recomputed from data each call, so no stored state is
needed and the same data always gives the same answer.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_HISTORY = 252  # trading days before percentiles are trusted


def _expanding_pct_rank(x: pd.Series) -> pd.Series:
    """Percentile of each value among all values up to and including that date."""
    vals = x.to_numpy()
    out = np.full(len(vals), np.nan)
    for i in range(len(vals)):
        if i + 1 >= MIN_HISTORY and np.isfinite(vals[i]):
            hist = vals[: i + 1]
            hist = hist[np.isfinite(hist)]
            out[i] = (hist <= vals[i]).mean()
    return pd.Series(out, index=x.index)


def conditions(spx: pd.Series, funding: pd.Series | None = None) -> pd.DataFrame:
    """Daily raw conditions (before hysteresis)."""
    spx = spx.dropna().sort_index()
    ret = spx.pct_change()
    vol21 = ret.rolling(21).std() * np.sqrt(252)
    vol_pct = _expanding_pct_rank(vol21)
    below_200 = spx < spx.rolling(200).mean()
    ret_12m = spx / spx.shift(252) - 1
    df = pd.DataFrame({"spx": spx, "vol21": vol21, "vol_pct": vol_pct,
                       "below_200dma": below_200, "ret_12m": ret_12m})
    if funding is not None and len(funding.dropna()):
        f = funding.dropna().sort_index().reindex(spx.index).ffill()
        df["funding_pct"] = _expanding_pct_rank(f)
    else:
        df["funding_pct"] = np.nan
    hot = (df["vol_pct"] > 0.8) | (df["funding_pct"] > 0.8)
    df["stress_raw"] = df["below_200dma"] & hot
    df["panic_raw"] = (df["ret_12m"] < 0) & (df["vol_pct"] > 0.8)
    return df


def weekly_flags(spx: pd.Series, funding: pd.Series | None = None, off_after: int = 2) -> pd.DataFrame:
    """Flags at each weekly check (last trading day of each week), with hysteresis."""
    c = conditions(spx, funding)
    wk = c.groupby(c.index.to_period("W")).tail(1)
    out = []
    state = {"stress": False, "panic": False}
    calm = {"stress": 0, "panic": 0}
    for d, row in wk.iterrows():
        for k in ("stress", "panic"):
            if bool(row[f"{k}_raw"]):
                state[k], calm[k] = True, 0
            elif state[k]:
                calm[k] += 1
                if calm[k] >= off_after:
                    state[k], calm[k] = False, 0
        out.append({"date": d, "stress": state["stress"], "panic": state["panic"],
                    "below_200dma": bool(row["below_200dma"]), "vol_pct": row["vol_pct"],
                    "funding_pct": row["funding_pct"], "ret_12m": row["ret_12m"]})
    return pd.DataFrame(out).set_index("date")


def flags_asof(spx: pd.Series, asof, funding: pd.Series | None = None) -> dict:
    """Flags at the last weekly check on or before `asof`, using data up to `asof` only."""
    asof = pd.Timestamp(asof)
    w = weekly_flags(spx[spx.index <= asof], None if funding is None else funding[funding.index <= asof])
    if w.empty:
        return {"stress": False, "panic": False}
    row = w.iloc[-1]
    return {k: (bool(v) if isinstance(v, (bool, np.bool_)) else (None if pd.isna(v) else float(v)))
            for k, v in row.items()} | {"checked": str(w.index[-1].date())}
