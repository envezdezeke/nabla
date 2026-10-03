"""nabla portfolio API. Judged paths and response shapes follow the starter template.

    export SV_DATA_ROOT=... SV_DATA_TOKEN=...      # token from the environment only
    uvicorn app.main:app --port 8000

/portfolio/holdings serves the frozen v1 book (config/book.json). When the data
has a newer trading day than the book, a background thread rebuilds it from the
same code, and the current book is served meanwhile, so the endpoint never waits
on a rebuild.
"""
from __future__ import annotations

import json
import math
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import polars as pl
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from statevector import Dataset, run_backtest  # noqa: E402
from statevector.backtest import REBALANCE_CHOICES  # noqa: E402

from nabla import data, live, model  # noqa: E402

BOOK = ROOT / "config" / "book.json"
STALE_CHECK_SECONDS = 600

ds = Dataset()
app = FastAPI(title="nabla portfolio api", version="1.0.0")
_lock = threading.Lock()
_state = {"checked": 0.0, "refreshing": False, "last_error": None}


def clean(records: list[dict]) -> list[dict]:
    """NaN/inf -> None so sparse fundamentals never 500 on json.dumps."""
    return [{k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in r.items()}
            for r in records]


def _read_book() -> dict | None:
    try:
        return json.loads(BOOK.read_text())
    except (OSError, ValueError):
        return None


def _refresh() -> None:
    try:
        fresh = Dataset()  # re-reads the remote manifest, so new days are visible
        book = live.build_book(fresh, model.load_config())
        BOOK.write_text(json.dumps(book, indent=2, default=str))
        _state["last_error"] = None
    except Exception as e:  # noqa: BLE001 - keep serving the last good book
        _state["last_error"] = f"{type(e).__name__}: {e}"
    finally:
        _state["refreshing"] = False


def _maybe_refresh(book: dict | None) -> None:
    now = time.time()
    with _lock:
        if _state["refreshing"] or now - _state["checked"] < STALE_CHECK_SECONDS:
            return
        _state["checked"] = now
        try:
            newest = str(data.last_trading_day(Dataset() if ds.base else ds))
        except Exception:  # noqa: BLE001
            return
        if book is None or book.get("as_of", "") < newest:
            _state["refreshing"] = True
            threading.Thread(target=_refresh, daemon=True).start()


def _fallback_book(n: int = 15) -> dict:
    """Starter logic (equal-weight most liquid), used only if no book exists yet."""
    asof = data.last_trading_day(ds)
    px = ds._scan("stocks_daily", start=str(asof - timedelta(days=45)), end=str(asof))
    top = (px.with_columns((pl.col("close") * pl.col("volume")).alias("dv"))
           .group_by("ticker").agg(pl.col("dv").tail(20).mean().alias("adv20"))
           .sort("adv20", descending=True).limit(n).collect())
    w = round(1.0 / len(top), 8) if len(top) else 0.0
    return {"as_of": str(asof), "model": "fallback", "method": "equal_weight_top_liquidity",
            "holdings": [{"ticker": t, "weight": w} for t in top["ticker"].to_list()]}


# ---------------------------------------------------------------- health -----

@app.get("/health")
def health() -> dict:
    book = _read_book()
    return {"ok": True, "model": model.load_config()["version"],
            "book_as_of": book.get("as_of") if book else None,
            "refreshing": _state["refreshing"], "last_refresh_error": _state["last_error"]}


# ------------------------------------------------------------- portfolio -----

@app.get("/portfolio/holdings")
def holdings() -> dict:
    book = _read_book()
    _maybe_refresh(book)
    if book is None:
        book = _fallback_book()
    return {k: book[k] for k in ("as_of", "model", "method", "holdings") if k in book}


@app.get("/model")
def model_card() -> dict:
    """Config, factor coverage and the top-30 candidates behind the current book."""
    book = _read_book() or {}
    return {"config": model.load_config(),
            **{k: book.get(k) for k in ("as_of", "coverage", "candidates", "notes")}}


# -------------------------------------------------------------- backtest -----

class BacktestRequest(BaseModel):
    tickers: list[str] = Field(min_length=1)
    weights: list[float] | None = None
    start: date
    end: date
    rebalance: str = "none"
    cost_bps: float | None = None


@app.post("/backtest")
def backtest(req: BacktestRequest) -> dict:
    """Same engine as the judges' recompute (statevector.run_backtest), net of fees."""
    if req.end <= req.start:
        raise HTTPException(400, "end must be after start")
    weights = req.weights or [1.0 / len(req.tickers)] * len(req.tickers)
    if len(weights) != len(req.tickers):
        raise HTTPException(400, "weights length must match tickers")
    if any(w < 0 for w in weights):
        raise HTTPException(400, "long-only: all weights must be >= 0")
    if abs(sum(weights) - 1.0) > 0.01:
        raise HTTPException(400, "weights must sum to ~1.0")
    if req.rebalance not in REBALANCE_CHOICES:
        raise HTTPException(400, f"rebalance must be one of {REBALANCE_CHOICES}")
    if req.cost_bps is not None and req.cost_bps < 0:
        raise HTTPException(400, "cost_bps must be >= 0")

    wide = (
        ds._scan("stocks_daily", start=str(req.start), end=str(req.end))
        .filter(pl.col("ticker").is_in(req.tickers) & pl.col("date").is_between(req.start, req.end))
        .select(["date", "ticker", "close"]).collect()
        .pivot(on="ticker", index="date", values="close").sort("date")
    )
    if wide.height < 3:
        raise HTTPException(400, "insufficient data in range")
    cols = [c for c in wide.columns if c != "date"]
    rets = wide.select([pl.col(c) / pl.col(c).shift(1) - 1.0 for c in cols]).fill_null(0.0)
    metrics = run_backtest(rets, wide["date"].to_list(), req.tickers, weights,
                           rebalance=req.rebalance, cost_bps=req.cost_bps)
    if not metrics:
        raise HTTPException(400, "no overlapping return days")
    return {"tickers": req.tickers, "weights": weights, "start": str(req.start), "end": str(req.end),
            "rebalance": req.rebalance,
            **{k: (round(v, 4) if k == "sharpe" else round(v, 6)) for k, v in metrics.items()}}


# ----------------------------------------------------------------- screen ----

@app.get("/screen")
def screen(min_adv: float = Query(0, description="min 20d avg dollar volume"),
           sector_contains: str | None = None, limit: int = Query(25, le=200)) -> dict:
    """Liquidity screen anchored to the last trading day in the data."""
    asof = data.last_trading_day(ds)
    px = ds._scan("stocks_daily", start=str(asof - timedelta(days=45)), end=str(asof))
    out = (px.with_columns((pl.col("close") * pl.col("volume")).alias("dv"))
           .group_by("ticker").agg(pl.col("dv").tail(20).mean().alias("adv20"))
           .filter(pl.col("adv20") >= min_adv).collect().to_pandas())
    if sector_contains:
        try:
            sec = ds.sectors()
            match = sec[sec["sic_description"].str.contains(sector_contains, case=False, na=False)]["ticker"]
            out = out[out["ticker"].isin(match)]
        except (FileNotFoundError, KeyError):
            pass
    out = out.sort_values("adv20", ascending=False).head(limit)
    return {"count": int(len(out)), "results": out.to_dict("records")}


# ------------------------------------------------------------------- asof ----

@app.get("/asof")
def asof(ticker: str, on: date):
    """PIT-safe fundamentals: what a model could have seen on `on`."""
    try:
        return clean(ds.fundamentals(ticker, asof=str(on)).to_dict("records"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))
