"""Fill the local Store from the Bloomberg Terminal.

Field choices below are unverified against a live Terminal until
scripts/bbg_ingest.py has run once; mnemonics a licence or ticker does not
carry come back empty and the model treats a missing factor as neutral.

Point in time:
- Prices are split-adjusted by Bloomberg; raw, unrestated closes are not
  available for the past, so a later split never reaches back into the store
  (adjusted history is re-pulled with `--full` if one happens).
- Fundamentals carry ANNOUNCEMENT_DT; it becomes report_calendar_us.filing_date,
  so a quarter counts only from the day after its announcement. Bloomberg
  restates fundamentals, so these rows are as restated today, not as first
  reported. That is a lookahead risk for backtests on the pulled history;
  forward test rows are safe because every pull is dated.
- guidance_range_velocity has no Bloomberg history. It is written empty (the
  guidance factor is neutral) until a replacement signal is chosen.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

PRICE_FIELDS = ["PX_OPEN", "PX_LAST", "PX_VOLUME"]
IV_FIELD = "30DAY_IMPVOL_100.0%MNY_DF"
FUND_FIELDS = ["IS_EPS", "SALES_REV_TURN", "GROSS_PROFIT", "IS_OPER_INC", "NET_INCOME",
               "CF_FREE_CASH_FLOW", "EBITDA", "BS_TOT_ASSET", "TOT_COMMON_EQY", "ANNOUNCEMENT_DT"]
INDEXES = {"SPX": "SPX Index"}
CHUNK = 25
DATE_COLS = ("date", "filing_date", "period_end")


def root_ticker(sec: str) -> str:
    """'BRK/B US Equity' -> 'BRK.B'"""
    return sec.removesuffix(" US Equity").replace("/", ".")


def chunks(xs: list, n: int = CHUNK):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def _long(df: pd.DataFrame, rename: dict[str, str]) -> pd.DataFrame:
    """Terminal history frame -> ticker, date, lower-case columns."""
    if df.empty:
        return df
    out = df.copy()
    out["ticker"] = out.pop("security").map(root_ticker)
    out["date"] = pd.to_datetime(out["date"])
    return out.rename(columns=rename)


def _merge(path: Path, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Append `new` to the table at `path`; on a repeated key the newer pull wins."""
    if path.exists():
        old = pl.read_parquet(path).to_pandas()
        new = pd.concat([old, new], ignore_index=True)
    for c in DATE_COLS:
        if c in new:
            new[c] = pd.to_datetime(new[c])
    new = new.drop_duplicates(keys, keep="last").sort_values(keys).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = new.copy()
    for c in DATE_COLS:
        if c in out:
            out[c] = pd.to_datetime(out[c]).dt.date
    pl.from_pandas(out).write_parquet(path)
    return new


def days_to_next_report(dates: pd.DataFrame, cal: pd.DataFrame) -> pd.Series:
    """Calendar days from each (ticker, date) to that ticker's next announcement on or after it."""
    out = pd.Series(np.nan, index=dates.index)
    nxt = cal.dropna(subset=["filing_date"]).sort_values("filing_date")
    for t, g in dates.groupby("ticker"):
        f = nxt.loc[nxt["ticker"] == t, "filing_date"].to_numpy("datetime64[D]")
        if not len(f):
            continue
        d = g["date"].to_numpy("datetime64[D]")
        i = np.searchsorted(f, d, side="left")
        ok = i < len(f)
        out.loc[g.index[ok]] = (f[i[ok]] - d[ok]).astype(int)
    return out


def run(term, tickers: list[str], start: date, end: date, root: Path, log=print) -> dict:
    """Pull [start, end] for `tickers` and merge it into the store at `root`."""
    canon, struct = root / "data" / "canonical", root / "data" / "structural"
    struct.mkdir(parents=True, exist_ok=True)
    (struct / "universe_us.txt").write_text("\n".join(tickers) + "\n")

    px, iv, fund = [], [], []
    for i, ch in enumerate(chunks(tickers)):
        log(f"  chunk {i + 1}/{-(-len(tickers) // CHUNK)}")
        px.append(_long(term.history(ch, PRICE_FIELDS, start, end),
                        {"PX_OPEN": "open", "PX_LAST": "close", "PX_VOLUME": "volume"}))
        iv.append(_long(term.history(ch, [IV_FIELD], start, end), {IV_FIELD: "atm_iv"}))
        fund.append(_long(term.history(ch, FUND_FIELDS, start, end, periodicity="QUARTERLY"),
                          {"ANNOUNCEMENT_DT": "filing_date"}))
    px, iv, fund = (pd.concat([p for p in x if len(p)], ignore_index=True) for x in (px, iv, fund))
    px = px.dropna(subset=["close"])[["ticker", "date", "open", "close", "volume"]]
    stocks = _merge(canon / "stocks_daily.parquet", px, ["ticker", "date"])

    fund.columns = [c.lower() for c in fund.columns]
    fund["period_end"] = fund["date"]
    fund["filing_date"] = pd.to_datetime(fund["filing_date"], errors="coerce")
    _merge(canon / "fundamentals_actuals.parquet", fund.drop(columns=["filing_date", "period_end"]),
           ["ticker", "date"])
    cal = _merge(struct / "report_calendar_us.parquet",
                 fund[["ticker", "filing_date", "period_end"]].assign(form_type="earnings")
                 .dropna(subset=["filing_date"]), ["ticker", "period_end"])

    sv = iv[["ticker", "date", "atm_iv"]].merge(stocks[["ticker", "date"]], on=["ticker", "date"], how="right")
    sv["days_to_next_report"] = days_to_next_report(sv, cal)
    sv["guidance_range_velocity"] = np.nan
    _merge(canon / "state_vector.parquet", sv, ["ticker", "date"])

    idx = []
    for name, sec in INDEXES.items():
        h = term.history([sec], ["PX_LAST"], start, end)
        h = h.assign(index=name, close=h["PX_LAST"], date=pd.to_datetime(h["date"]))
        idx.append(h[["index", "date", "close"]])
    _merge(canon / "index_daily.parquet", pd.concat(idx, ignore_index=True), ["index", "date"])

    return {"stock_rows": len(px), "tickers": px["ticker"].nunique(),
            "fundamental_rows": len(fund), "last_day": str(px["date"].max().date())}
