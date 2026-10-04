"""A small dataset root in the statevector layout, for tests with no network.

Includes a planted signal (guidance velocity predicts next-week returns),
one unadjusted 4-for-1 split, a reference table with SIC codes, SPX, and a
filing calendar so every v1 code path runs.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl


def build(root: Path, n_tickers: int = 80, start: str = "2019-01-02", end: str = "2026-09-30",
          seed: int = 0) -> Path:
    rng = np.random.default_rng(seed)
    root = Path(root)
    for d in ("data/canonical", "data/structural", "data/raw/massive"):
        (root / d).mkdir(parents=True, exist_ok=True)
    days = pd.bdate_range(start, end)
    n = len(days)
    T = ["AAPL", "MSFT"] + [f"T{i:03d}" for i in range(2, n_tickers)]  # rubric uses AAPL, MSFT
    sig = rng.normal(size=(n, n_tickers))
    # planted: today's signal shifts the next 5 days' drift
    drift = np.zeros_like(sig)
    for k in range(1, 6):
        drift[k:] += 0.0008 * sig[:-k]
    ret = 0.0003 + drift + rng.normal(0, 0.015, size=(n, n_tickers))
    close = 50 * np.cumprod(1 + ret, axis=0)
    split_t, split_i = "T005", n // 2
    close[split_i:, 5] /= 4.0  # raw series shows the 4-for-1 drop
    vol = np.full((n, n_tickers), 2e6)
    vol[split_i:, 5] *= 4
    dd = days.values.astype("datetime64[D]")
    d_col = np.repeat(dd, n_tickers)
    t_col = np.tile(T, n)
    opn = close * (1 + rng.normal(0, 0.003, size=close.shape))
    pl.DataFrame({"ticker": t_col, "date": d_col, "open": opn.ravel(), "close": close.ravel(),
                  "volume": vol.ravel()}) \
        .write_parquet(root / "data/canonical/stocks_daily.parquet")
    rv = 0.015 * np.sqrt(252)
    pl.DataFrame({
        "ticker": t_col, "date": d_col,
        "guidance_range_velocity": sig.ravel(),
        "atm_iv": rv * np.exp(rng.normal(0, 0.2, n * n_tickers)),
        "log_fv_gap": rng.normal(0, 0.5, n * n_tickers),
        "days_to_next_report": rng.integers(0, 91, n * n_tickers).astype(float),
    }).write_parquet(root / "data/canonical/state_vector.parquet")
    pl.DataFrame({"ticker": [split_t], "ex_date": [days[split_i].date()], "kind": ["split"],
                  "value": [4.0], "raw": [""]}).write_parquet(root / "data/structural/corporate_actions.parquet")
    sic = rng.choice([2834, 3674, 7372, 6022, 4911, 5331, 1311, 3711, 4813, 8062], size=n_tickers)
    pl.DataFrame({"ticker": T, "name": T, "sic_code": [str(s) for s in sic],
                  "sic_description": ["x"] * n_tickers, "primary_exchange": ["XNYS"] * n_tickers,
                  "market_cap": [1e10] * n_tickers}).write_parquet(root / "data/raw/massive/reference_tickers.parquet")
    spx = 3000 * np.cumprod(1 + rng.normal(0.0004, 0.01, n))
    pl.DataFrame({"index": ["SPX"] * n, "date": dd, "close": spx}) \
        .write_parquet(root / "data/canonical/index_daily.parquet")
    pl.DataFrame([{"ticker": "AAPL", "date": date(2024, 2, 1), "revenue": 1e9}]) \
        .write_parquet(root / "data/canonical/fundamentals_actuals.parquet")
    pl.DataFrame([{"ticker": "AAPL", "filing_date": date(2024, 2, 10), "form_type": "10-Q",
                   "accession_number": "x"}]).write_parquet(root / "data/structural/report_calendar_us.parquet")
    (root / "data/structural/universe_us.txt").write_text("\n".join(T) + "\n")
    return root
