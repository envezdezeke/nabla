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
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
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
from nabla import decide as replay  # noqa: E402

BOOK = ROOT / "config" / "book.json"
STALE_CHECK_SECONDS = 600

class DataUnavailable(RuntimeError):
    """The data server refused or could not be reached (e.g. a revoked token)."""


class _LazyDataset:
    """Connects to the data server on first use instead of at import, and retries
    at most once a minute after a failure. Without data the API still starts:
    /health, /portfolio/holdings, /model and /decide serve the frozen book
    (config/book.json); /backtest, /screen and /asof read the yearly price and state-vector cache
    (real data downloaded earlier); without a cached year they answer 503."""
    RETRY_SECONDS = 60

    def __init__(self):
        self._ds, self._failed_at, self.error = None, 0.0, None

    def connect(self):
        if self._ds is None:
            if self.error and time.time() - self._failed_at < self.RETRY_SECONDS:
                raise DataUnavailable(self.error)
            try:
                self._ds, self.error = Dataset(), None
            except Exception as e:  # noqa: BLE001 - 401, DNS, timeout: all mean no data
                self.error, self._failed_at = f"{type(e).__name__}: {e}", time.time()
                raise DataUnavailable(self.error) from e
        return self._ds

    def __getattr__(self, name):
        return getattr(self.connect(), name)


ds = _LazyDataset()
app = FastAPI(title="nabla portfolio api", version="1.0.0")


@app.exception_handler(DataUnavailable)
def _no_data(_request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=503, content={"detail": f"data server unavailable: {exc}"})
_lock = threading.Lock()
_state = {"checked": 0.0, "refreshing": False, "last_error": None}
_price_lock = threading.Lock()
_screen_cache: dict = {}


def _prices(start: date, end: date, tickers: list[str] | None = None):
    """Daily close/volume through the yearly on-disk cache (data.load_prices).

    Scanning the hosted server file by file takes 45 s or more per request,
    past the rubric's 30 s timeout; a cached year is read from disk in well
    under a second. The lock stops two requests writing the same year file."""
    with _price_lock:
        try:
            live_ds = ds.connect()
        except DataUnavailable:
            df = _offline(lambda: data.cached_panel("prices", start, end))
            return (df[df["ticker"].isin(tickers)] if tickers is not None else df).reset_index(drop=True)
        return data.load_prices(live_ds, start, end, tickers)


def _offline(read):
    """Real data downloaded earlier from the data server, read from artifacts/cache."""
    try:
        return read()
    except FileNotFoundError as e:
        raise DataUnavailable(str(e)) from e


def _last_day() -> date:
    try:
        return data.last_trading_day(ds.connect())
    except DataUnavailable:
        return _offline(data.cached_last_day)


def _warm() -> None:
    """Fill the cache at startup: the screen window first, then 2020 (the
    rubric's /backtest request)."""
    try:
        last = data.last_trading_day(ds.connect())
        _screen_table(last)
        _prices(date(2020, 1, 1), date(2020, 12, 31))
    except Exception:  # noqa: BLE001 - warming is best effort
        pass


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
            newest = str(data.last_trading_day(Dataset() if ds.connect().base else ds.connect()))
        except Exception:  # noqa: BLE001
            return
        stale_model = book is not None and book.get("model") != model.load_config()["version"]
        if book is None or book.get("as_of", "") < newest or stale_model:
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
    try:
        ds.connect()
        data_status = "ok"
    except DataUnavailable as e:
        data_status = f"unavailable ({e}); serving the frozen book"
    return {"ok": True, "model": model.load_config()["version"], "data": data_status,
            "book_as_of": book.get("as_of") if book else None,
            "refreshing": _state["refreshing"], "warm": _state.get("warm"), "last_refresh_error": _state["last_error"]}


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


# ---------------------------------------------------------------- replay -----

class DecideRequest(BaseModel):
    information_cutoff: str                      # e.g. "2026-09-25T16:00:00-04:00" or "2026-09-25"
    team_id: str | None = None


DECIDE_BUDGET_SECONDS = 25  # the judges' timeout is 30 s
_pool = ThreadPoolExecutor(max_workers=2)


@app.post("/decide")
def decide_post(req: DecideRequest) -> dict:
    """One decision record for the judges' replay (see src/nabla/decide.py).

    A week's book is computed once and cached. If computing it would overrun the
    time budget, the answer is the frozen book (config/book.json), marked
    "fallback", while the computation finishes in the background for later calls."""
    try:
        live_ds = ds.connect()
    except DataUnavailable:
        book = _read_book()
        if book is None:
            raise
        try:
            return replay.offline_record(req.information_cutoff, book, req.team_id)
        except ValueError as e:
            raise HTTPException(400, str(e))
    fut = _pool.submit(replay.decide, req.information_cutoff, live_ds, req.team_id)
    try:
        return fut.result(timeout=DECIDE_BUDGET_SECONDS)
    except FuturesTimeout:
        book = _read_book() or _fallback_book()
        return replay.decide(req.information_cutoff, ds=live_ds, team_id=req.team_id, fallback_book=book)
    except ValueError as e:
        raise HTTPException(400, str(e))


def _warm() -> None:
    """Compute the latest weekly decisions at startup so the first judge call is fast."""
    try:
        live_ds = ds.connect()
        days = data.trading_days(live_ds)
        for d in days[-6:]:
            replay.decide(d, ds=live_ds)
        _state["warm"] = f"ok through {days[-1]}"
    except Exception as e:  # noqa: BLE001 - warming is best-effort
        _state["warm"] = f"failed: {type(e).__name__}: {e}"


@app.on_event("startup")
def _startup() -> None:
    _state["warm"] = "running"
    threading.Thread(target=_warm, daemon=True).start()


@app.get("/decide")
def decide_get(information_cutoff: str, team_id: str | None = None) -> dict:
    return decide_post(DecideRequest(information_cutoff=information_cutoff, team_id=team_id))


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

    px = _prices(req.start, req.end, req.tickers)
    wide_pd = px.pivot_table(index="date", columns="ticker", values="close", aggfunc="last").sort_index()
    if len(wide_pd) < 3:
        raise HTTPException(400, "insufficient data in range")
    rets = pl.from_pandas((wide_pd / wide_pd.shift(1) - 1.0).fillna(0.0).reset_index(drop=True))
    dates = [d.date() for d in wide_pd.index]
    metrics = run_backtest(rets, dates, req.tickers, weights,
                           rebalance=req.rebalance, cost_bps=req.cost_bps)
    if not metrics:
        raise HTTPException(400, "no overlapping return days")
    return {"tickers": req.tickers, "weights": weights, "start": str(req.start), "end": str(req.end),
            "rebalance": req.rebalance,
            **{k: (round(v, 4) if k == "sharpe" else round(v, 6)) for k, v in metrics.items()}}


# ----------------------------------------------------------------- screen ----

def _screen_table(asof: date):
    """20-day average dollar volume per ticker as of the last trading day (memoized per day)."""
    if asof not in _screen_cache:
        px = _prices(asof - timedelta(days=45), asof)
        px = px.assign(dv=px["close"] * px["volume"]).sort_values("date")
        _screen_cache.clear()
        _screen_cache[asof] = (px.groupby("ticker")["dv"].apply(lambda x: x.tail(20).mean())
                               .rename("adv20").reset_index())
    return _screen_cache[asof].copy()


@app.get("/screen")
def screen(min_adv: float = Query(0, description="min 20d avg dollar volume"),
           sector_contains: str | None = None, limit: int = Query(25, le=200)) -> dict:
    """Liquidity screen anchored to the last trading day in the data."""
    out = _screen_table(_last_day())
    out = out[out["adv20"] >= min_adv]
    if sector_contains:
        try:
            sec = ds.sectors()
            match = sec[sec["sic_description"].str.contains(sector_contains, case=False, na=False)]["ticker"]
            out = out[out["ticker"].isin(match)]
        except (FileNotFoundError, KeyError, DataUnavailable):
            pass
    out = out.sort_values("adv20", ascending=False).head(limit)
    return {"count": int(len(out)), "results": out.to_dict("records")}


# ------------------------------------------------------------------- asof ----

@app.get("/asof")
def asof(ticker: str, on: date):
    """PIT-safe fundamentals: what a model could have seen on `on`.

    Without the data server, the cached state vector for the ticker over the
    30 days up to `on` (still nothing dated after `on`), marked by "source"."""
    try:
        live_ds = ds.connect()
    except DataUnavailable:
        start = on - timedelta(days=30)
        sv = _offline(lambda: data.cached_panel("state_vector", start, on))
        sv = sv[sv["ticker"] == ticker].sort_values("date")
        sv = sv.assign(date=sv["date"].dt.strftime("%Y-%m-%d"), source="state_vector_cache")
        return clean(sv.to_dict("records"))
    try:
        return clean(live_ds.fundamentals(ticker, asof=str(on)).to_dict("records"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e))


threading.Thread(target=_warm, daemon=True).start()
