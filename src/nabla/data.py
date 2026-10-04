"""Data access on top of the statevector SDK.

Every loader takes an explicit as-of window. The as-of date is the last
trading day in the data (never date.today()), so the book is reproducible and
nothing after the decision date is read.
"""
from __future__ import annotations

import re
from pathlib import Path
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


CACHE = Path(__file__).resolve().parents[2] / "artifacts" / "cache"


def _cached_years(name: str, start: date, end: date, fetch) -> pd.DataFrame:
    """Fetch a panel one calendar year at a time, keeping each year on disk.

    The remote server serves one file per trading day, so a multi-year backtest
    downloads thousands of files. A cached year is reused if it reaches the
    requested end (or the year is over); otherwise it is fetched again.
    Delete artifacts/cache to force a fresh download.
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    parts = []
    for y in range(start.year, end.year + 1):
        a, b = max(start, date(y, 1, 1)), min(end, date(y, 12, 31))
        f = CACHE / f"{name}_{y}.parquet"
        df = pd.read_parquet(f) if f.exists() else None
        # stale = the requested end is more than a long weekend past the cached last day
        # (the old test also required min(date) <= Jan 1, a holiday, so it never fired)
        if df is None or (y == end.year and len(df)
                          and df["date"].max() < pd.Timestamp(b) - pd.Timedelta(days=4)):
            print(f"  downloading {name} {y} ...", flush=True)
            df = fetch(date(y, 1, 1), min(end, date(y, 12, 31)) if y == end.year else date(y, 12, 31))
            df.to_parquet(f)
        parts.append(df[(df["date"] >= pd.Timestamp(a)) & (df["date"] <= pd.Timestamp(b))])
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def load_prices(ds, start: date, end: date, tickers: list[str] | None = None) -> pd.DataFrame:
    """Long frame ticker, date, close, volume for [start, end] (cached by year)."""
    def fetch(a, b):
        lf = ds.get("stocks_daily", start=str(a), end=str(b), limit=BIG, lazy=True)
        df = lf.select(["ticker", "date", "close", "volume"]).collect().to_pandas()
        df["date"] = pd.to_datetime(df["date"])
        return df
    df = _cached_years("prices", start, end, fetch) if getattr(ds, "base", None) else fetch(start, end)
    if tickers is not None:
        df = df[df["ticker"].isin(tickers)]
    return df.reset_index(drop=True)


def load_opens(ds, start: date, end: date) -> pd.DataFrame:
    """Long frame ticker, date, open for [start, end] (own yearly cache, so the
    close/volume cache stays unchanged). Used only by next-open fill tests."""
    def fetch(a, b):
        lf = ds.get("stocks_daily", start=str(a), end=str(b), limit=BIG, lazy=True)
        df = lf.select(["ticker", "date", "open"]).collect().to_pandas()
        df["date"] = pd.to_datetime(df["date"])
        return df
    return _cached_years("opens", start, end, fetch) if getattr(ds, "base", None) else fetch(start, end)


def adjust_like(raw: pd.DataFrame, raw_close: pd.DataFrame, adj_close: pd.DataFrame) -> pd.DataFrame:
    """Apply the split adjustment of adj_close/raw_close to another price field (e.g. open)."""
    f = (adj_close / raw_close).reindex_like(raw)
    return raw * f.fillna(1.0)


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


def load_fundamentals(ds, tickers: list[str]) -> tuple[pd.DataFrame | None, dict]:
    """Filed quarterly fundamentals with the time each row became public."""
    from . import fundamentals
    try:
        fund = ds.get("fundamentals_actuals", limit=BIG)
    except Exception as e:  # noqa: BLE001 - optional panel; quality goes neutral
        return None, {"fundamentals": f"unavailable: {type(e).__name__}"}
    fund = fund[fund["ticker"].isin(tickers)]
    try:
        cal = ds._scan("report_calendar_us").collect().to_pandas()
    except Exception:  # noqa: BLE001 - no calendar: every row uses the 60-day lag
        cal = None
    f, notes = fundamentals.prepare(fund, cal)
    notes["fundamental_rows"] = int(len(f))
    notes["filing_calendar"] = cal is not None
    return f, notes


SV_COLS = ["guidance_range_velocity", "atm_iv", "log_fv_gap", "days_to_next_report"]


def load_state_vector(ds, start: date, end: date, dates: list | None = None) -> pd.DataFrame:
    """State-vector columns used by v1, optionally only on the given dates."""
    def fetch(a, b):
        lf = ds.state_vector(start=str(a), end=str(b), lazy=True)
        have = lf.collect_schema().names()
        cols = ["ticker", "date"] + [c for c in SV_COLS if c in have]
        df = lf.select(cols).collect().to_pandas()
        df["date"] = pd.to_datetime(df["date"])
        return df
    df = _cached_years("state_vector", start, end, fetch) if getattr(ds, "base", None) else fetch(start, end)
    if dates is not None:
        df = df[df["date"].isin(pd.to_datetime(list(dates)))]
    return df.reset_index(drop=True)


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


def return_clusters(close: pd.DataFrame, k: int = 10, window: int = 252, seed: int = 0) -> pd.Series:
    """Sector groups from co-movement, for when the data has no industry codes.

    Uses only the `window` days of returns at the end of `close` (pass prices
    ending at the decision start, so labels never use later data). Each stock is
    described by its loadings on the top k principal components of standardized
    returns, then k-means (k-means++ start, fixed seed) assigns k groups.
    Stocks without a full window are "other" (uncapped).
    """
    r = close.pct_change(fill_method=None).iloc[-window:]
    r = r.loc[:, r.notna().mean() > 0.9].fillna(0.0)
    out = pd.Series("other", index=close.columns, dtype=object)
    if r.shape[1] < k * 3:
        return out
    z = ((r - r.mean()) / r.std().replace(0, np.nan)).fillna(0.0).to_numpy()
    _, _, vt = np.linalg.svd(z, full_matrices=False)
    x = vt[:k].T  # stock loadings on the top k components
    x = x / np.linalg.norm(x, axis=1, keepdims=True).clip(1e-12)
    rng = np.random.default_rng(seed)
    centers = [x[rng.integers(len(x))]]
    for _ in range(1, k):
        d = np.min([((x - c) ** 2).sum(1) for c in centers], axis=0)
        centers.append(x[rng.choice(len(x), p=d / d.sum())])
    c = np.array(centers)
    for _ in range(100):
        lab = ((x[:, None, :] - c[None]) ** 2).sum(2).argmin(1)
        new = np.array([x[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
        if np.allclose(new, c):
            break
        c = new
    out[r.columns] = [f"cluster{j}" for j in lab]
    return out
