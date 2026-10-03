"""Data access on top of the statevector SDK.

Every loader takes an explicit as-of window. The as-of date is the last
trading day in the data (never date.today()), so the book is reproducible and
nothing after the decision date is read.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import numpy as np
import pandas as pd
import polars as pl

BIG = 2**31 - 1  # ds.get silently caps partitioned panels at 10k rows without a limit


def trading_days(ds) -> list[date]:
    """Trading days from the remote manifest (cheap) or a local date scan."""
    if getattr(ds, "base", None):
        files = ds._index["panels"]["stocks_daily"]["files"]
        stems = (re.search(r"(\d{4}-\d{2}-\d{2})\.parquet$", f) for f in files)
        return sorted(date.fromisoformat(m.group(1)) for m in stems if m)
    return list(ds.trading_days())


def last_trading_day(ds) -> date:
    return trading_days(ds)[-1]


def load_prices(ds, start: date, end: date, tickers: list[str] | None = None) -> pd.DataFrame:
    """Long frame ticker, date, close, volume for [start, end]."""
    lf = ds.get("stocks_daily", start=str(start), end=str(end), limit=BIG, lazy=True)
    if tickers is not None:
        lf = lf.filter(pl.col("ticker").is_in(tickers))
    df = lf.select(["ticker", "date", "close", "volume"]).collect().to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    return df


def to_wide(long: pd.DataFrame, col: str) -> pd.DataFrame:
    return long.pivot_table(index="date", columns="ticker", values=col, aggfunc="last").sort_index()


def split_adjust(close: pd.DataFrame, volume: pd.DataFrame, splits: pd.DataFrame,
                 tol: float = 0.25) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Back-adjust prices for splits, but only where the raw series shows the jump.

    `splits` has ticker, ex_date, value (to/from ratio; 2-for-1 -> 2.0). If the
    close on the ex-date already reflects adjustment (no ~1/ratio drop), the split
    is skipped, so this is safe on adjusted and unadjusted data alike.
    """
    close, volume = close.copy(), volume.copy()
    applied = skipped = 0
    for row in splits.itertuples(index=False):
        t, r = row.ticker, float(row.value)
        if t not in close.columns or not np.isfinite(r) or r <= 0 or abs(np.log(r)) < 0.05:
            continue
        s = close[t].dropna()
        pos = s.index.searchsorted(pd.Timestamp(row.ex_date))
        if pos == 0 or pos >= len(s):
            continue
        jump = s.iloc[pos] / s.iloc[pos - 1]
        if abs(np.log(jump * r)) < tol:  # raw series dropped by ~1/r: unadjusted
            before = close.index < s.index[pos]
            close.loc[before, t] /= r
            volume.loc[before, t] *= r
            applied += 1
        else:
            skipped += 1
    return close, volume, {"splits_applied": applied, "splits_already_adjusted": skipped}


def load_splits(ds) -> pd.DataFrame:
    try:
        ca = ds.structural("corporate_actions")
    except Exception:  # noqa: BLE001 - table optional in fixtures
        return pd.DataFrame(columns=["ticker", "ex_date", "value"])
    return ca[ca["kind"] == "split"][["ticker", "ex_date", "value"]]


SV_COLS = ["guidance_range_velocity", "atm_iv", "log_fv_gap", "days_to_next_report"]


def load_state_vector(ds, start: date, end: date, dates: list | None = None) -> pd.DataFrame:
    """State-vector columns used by v1, optionally only on the given dates."""
    lf = ds.state_vector(start=str(start), end=str(end), lazy=True)
    have = lf.collect_schema().names()
    cols = ["ticker", "date"] + [c for c in SV_COLS if c in have]
    if dates is not None:
        lf = lf.filter(pl.col("date").cast(pl.Date).is_in([pd.Timestamp(d).date() for d in dates]))
    df = lf.select(cols).collect().to_pandas()
    df["date"] = pd.to_datetime(df["date"])
    return df


# SIC two-digit code -> about 10 sector groups
_SIC_GROUPS = [
    (1, 14, "materials_energy"), (15, 17, "industrials"), (20, 27, "consumer_staples"),
    (28, 28, "pharma_chemicals"), (29, 34, "materials_energy"), (35, 36, "tech_hardware"),
    (37, 39, "industrials"), (40, 47, "industrials"), (48, 48, "communications"),
    (49, 49, "utilities"), (50, 59, "consumer_trade"), (60, 67, "financials"),
    (70, 72, "consumer_trade"), (73, 73, "software_services"), (74, 79, "consumer_trade"),
    (80, 80, "health_services"), (81, 99, "software_services"),
]
_KEYWORDS = [
    ("pharma_chemicals", "pharm|biolog|chemical|drug"), ("tech_hardware", "semiconductor|computer|electronic"),
    ("software_services", "software|prepackaged|data processing|services-"), ("financials", "bank|insur|invest|finance|reit|real estate"),
    ("utilities", "electric|gas|water|utilit"), ("communications", "telephone|communication|broadcast|cable"),
    ("materials_energy", "oil|petroleum|mining|metal|steel|crude"), ("health_services", "health|hospital|medical"),
    ("consumer_trade", "retail|wholesale|store|restaurant|eating"),
]


def sector_groups(ds, tickers: list[str]) -> pd.Series:
    """ticker -> sector group. SIC code ranges when available, else description keywords."""
    try:
        ref = ds.get("reference_tickers", limit=BIG)
    except Exception:  # noqa: BLE001
        return pd.Series("all", index=tickers)
    ref = ref.drop_duplicates("ticker").set_index("ticker")
    out = pd.Series("other", index=tickers, dtype=object)
    if "sic_code" in ref.columns:
        code = pd.to_numeric(ref["sic_code"], errors="coerce").reindex(tickers) // 100
        for lo, hi, g in _SIC_GROUPS:
            out[(code >= lo) & (code <= hi)] = g
    elif "sic_description" in ref.columns:
        desc = ref["sic_description"].reindex(tickers).fillna("").str.lower()
        for g, pat in _KEYWORDS:
            out[(out == "other") & desc.str.contains(pat)] = g
    return out


def spx_close(ds) -> pd.Series:
    try:
        b = ds.benchmark("SPX")
    except Exception:  # noqa: BLE001
        return pd.Series(dtype=float)
    return pd.Series(b["close"].values, index=pd.to_datetime(b["date"])).sort_index()


def window_start(asof: date, trading_days_needed: int) -> date:
    """Calendar start that covers `trading_days_needed` trading days before asof."""
    return asof - timedelta(days=int(trading_days_needed * 1.5) + 10)
