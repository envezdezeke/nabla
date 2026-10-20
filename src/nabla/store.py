"""Local parquet data store: the model's only data source.

Replaces the statevector SDK. Same methods the model code calls (`get`,
`universe`, `trading_days`, `holidays`, `structural`, `state_vector`,
`benchmark`, `_scan`), same on-disk layout, so loaders in data.py did not
change. Tables are written by scripts/bbg_ingest.py from the Bloomberg
Terminal; nothing here talks to a network.

Root: $NABLA_DATA_ROOT, default <repo>/artifacts/bbg.
  data/canonical/<panel>.parquet    stocks_daily, state_vector, index_daily, fundamentals_actuals
  data/structural/<table>.parquet   corporate_actions, report_calendar_us, market_holidays
  data/structural/universe_us.txt   one ticker per line
  data/raw/massive/reference_tickers.parquet   sic_code / sic_description / name
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import polars as pl

DEFAULT_ROOT = Path(__file__).resolve().parents[2] / "artifacts" / "bbg"
BIG = 2**31 - 1


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


class Store:
    base = None  # no remote server: data.py reads straight from disk and skips its yearly cache

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("NABLA_DATA_ROOT") or DEFAULT_ROOT)
        if not (self.root / "data").is_dir():
            raise FileNotFoundError(f"no data under {self.root}; run scripts/bbg_ingest.py")

    def _scan(self, name: str, start=None, end=None) -> pl.LazyFrame:
        for sub in ("canonical", "structural", "raw/massive"):
            p = self.root / "data" / sub / f"{name}.parquet"
            if p.exists():
                return pl.scan_parquet(p)
        raise KeyError(f"unknown table {name!r} under {self.root}")

    def get(self, panel: str, ticker: str | None = None, start=None, end=None,
            limit: int | None = None, lazy: bool = False):
        lf = self._scan(panel)
        cols = lf.collect_schema().names()
        if ticker:
            lf = lf.filter(pl.col("ticker") == ticker)
        if start and "date" in cols:
            lf = lf.filter(pl.col("date") >= _as_date(start))
        if end and "date" in cols:
            lf = lf.filter(pl.col("date") <= _as_date(end))
        if limit is not None:
            lf = lf.limit(limit)
        return lf if lazy else lf.collect().to_pandas()

    def universe(self, us_only: bool = True) -> list[str]:
        txt = self.root / "data/structural/universe_us.txt"
        return [t.strip() for t in txt.read_text().splitlines() if t.strip()]

    def structural(self, name: str) -> pd.DataFrame:
        p = self.root / "data/structural" / f"{name}.parquet"
        if not p.exists():
            raise KeyError(f"unknown structural table {name!r}")
        return pl.read_parquet(p).to_pandas()

    def state_vector(self, ticker=None, start=None, end=None, pca: bool = False, lazy: bool = False):
        return self.get("state_vector", ticker=ticker, start=start, end=end, lazy=lazy)

    def benchmark(self, index: str = "SPX") -> pd.DataFrame:
        return self._scan("index_daily").filter(pl.col("index") == index).sort("date").collect().to_pandas()

    def trading_days(self, start=None, end=None) -> list:
        lf = self._scan("stocks_daily").select("date").unique().sort("date")
        if start:
            lf = lf.filter(pl.col("date") >= _as_date(start))
        if end:
            lf = lf.filter(pl.col("date") <= _as_date(end))
        return lf.collect().to_series().to_list()

    def holidays(self) -> pd.DataFrame:
        return self._scan("market_holidays").collect().to_pandas()

    def sectors(self) -> pd.DataFrame:
        return self._scan("reference_tickers").collect().to_pandas()


def open(root: str | Path | None = None) -> Store:  # noqa: A001 - mirrors Dataset()
    return Store(root)
