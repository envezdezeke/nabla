"""The judges' replay interface: decide(information_cutoff) -> decision record.

The judges replay the frozen model one step at a time through the holdout. Each
call gets an information cutoff (a timestamp, default 16:00 ET) and returns one
complete target portfolio.

Rules:
  * Only data on or before the cutoff is read. If the cutoff is before 16:00 ET,
    that day's close is not yet known, so the previous trading day is the last
    data day. Never date.today(), never "the latest day in the data".
  * The book trades weekly. On the last trading day of a week the record says
    "rebalance" with a fresh target; on other days it says "hold" and repeats the
    target from that week's decision, so daily calls do not create daily trades.
  * Execution is the next trading day's open (09:30 ET).
  * No stored state: the entry/exit bands and the no-trade band need last week's
    book, so every call replays its own last 8 weekly decisions from the data.
  * Weights sum to 1 with cash as the CASHHOLDING ticker.
"""
from __future__ import annotations

import json
import os
import time as _time
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import data, live, model

ET = ZoneInfo("America/New_York")
SCHEMA_VERSION = "1.0"
CLOSE = time(16, 0)
OPEN = time(9, 30)


def _parse_cutoff(cutoff) -> datetime:
    """Timestamp in ET. A bare date means 16:00 ET that day; a naive datetime is ET."""
    if isinstance(cutoff, date) and not isinstance(cutoff, datetime):
        return datetime.combine(cutoff, CLOSE, ET)
    ts = pd.Timestamp(cutoff)
    if len(str(cutoff)) <= 10:  # "YYYY-MM-DD"
        return datetime.combine(ts.date(), CLOSE, ET)
    ts = ts.tz_localize(ET) if ts.tzinfo is None else ts.tz_convert(ET)
    return ts.to_pydatetime()


def _holidays(ds) -> set[date]:
    try:
        h = ds.holidays()
        col = "date" if "date" in h else h.columns[0]
        closed = h if "status" not in h else h[h["status"].astype(str).str.lower().eq("closed")]
        return set(pd.to_datetime(closed[col]).dt.date)
    except Exception:  # noqa: BLE001 - calendar optional; weekends still skipped
        return set()


def _closed_inside(days: list[date]) -> set[date]:
    """Weekdays inside the data's range with no trading: holidays the calendar
    panel may not list (e.g. Labor Day)."""
    have = set(days)
    out, d = set(), days[0]
    while d < days[-1]:
        if d.weekday() < 5 and d not in have:
            out.add(d)
        d += timedelta(days=1)
    return out


def next_trading_day(d: date, holidays: set[date]) -> date:
    d += timedelta(days=1)
    while d.weekday() >= 5 or d in holidays:
        d += timedelta(days=1)
    return d


def execution_day(decision_time: datetime, holidays: set[date]) -> date:
    """First trading day whose 09:30 ET open is after the decision (never before it)."""
    d = decision_time.date()
    if d.weekday() < 5 and d not in holidays and decision_time.time() < OPEN:
        return d
    return next_trading_day(d, holidays)


def last_data_day(cutoff: datetime, days: list[date]) -> date:
    """Last trading day whose close is known at the cutoff."""
    d = cutoff.date() if cutoff.time() >= CLOSE else cutoff.date() - timedelta(days=1)
    known = [x for x in days if x <= d]
    if not known:
        raise ValueError(f"no data on or before {d}")
    return known[-1]


def is_rebalance_day(d: date, holidays: set[date]) -> bool:
    """Last trading day of its ISO week: the next session falls in a new week."""
    return next_trading_day(d, holidays).isocalendar()[:2] != d.isocalendar()[:2]


def week_decision_day(d: date, days: list[date], holidays: set[date]) -> date:
    """The weekly decision in force on day d: d itself if it is the last trading
    day of its week, else the last trading day of the previous week."""
    if is_rebalance_day(d, holidays):
        return d
    prior = [x for x in days if x < d and is_rebalance_day(x, holidays)]
    return prior[-1] if prior else d


_DS: dict = {}
_BOOKS: dict = {}  # (dataset, decision day, model version) -> book; the replay calls the same week many times
BOOK_DIR = Path(__file__).resolve().parents[2] / "artifacts" / "books"


def _book_key(ds, decided: date, version: str):
    return (getattr(ds, "base", None) or id(ds), decided, version)


def _stored(ds, decided: date, version: str) -> dict | None:
    """A weekly book computed earlier (memory, then disk for the remote dataset).
    A book depends only on data on or before its decision day, so it never goes stale."""
    key = _book_key(ds, decided, version)
    if key in _BOOKS:
        return _BOOKS[key]
    f = BOOK_DIR / f"{version}_{decided}.json"
    if getattr(ds, "base", None) and f.exists():
        try:
            _BOOKS[key] = json.loads(f.read_text())
            return _BOOKS[key]
        except ValueError:
            return None
    return None


def _compute(ds, decided: date, cfg: dict) -> dict:
    book = live.build_book(ds, cfg, asof=decided)
    _BOOKS[_book_key(ds, decided, cfg["version"])] = book
    if getattr(ds, "base", None):
        BOOK_DIR.mkdir(parents=True, exist_ok=True)
        (BOOK_DIR / f"{cfg['version']}_{decided}.json").write_text(json.dumps(book, default=str))
    return book


def _dataset(root: str):
    from statevector import Dataset
    if root not in _DS:
        _DS[root] = Dataset(root)
    return _DS[root]


def offline_record(information_cutoff, book: dict, team_id: str | None = None) -> dict:
    """Decision record from the frozen book when the data server is unreachable.
    Weekends are skipped but exchange holidays are unknown, and the holdings are
    the frozen book whatever the cutoff; the record says so in "fallback"."""
    cfg = model.load_config()
    cutoff = _parse_cutoff(information_cutoff)
    today = cutoff.date()
    while today.weekday() >= 5:
        today -= timedelta(days=1)
    decision_time = cutoff + timedelta(minutes=15)
    execute = execution_day(decision_time, set())
    model_id = f"nabla-{cfg['version']}"
    return {
        "schema_version": SCHEMA_VERSION,
        "team_id": team_id or os.environ.get("NABLA_TEAM_ID", "nabla"),
        "model_id": model_id,
        "decision_id": f"{model_id}-{cutoff.date().isoformat()}",
        "information_cutoff": cutoff.isoformat(),
        "decision_time": decision_time.isoformat(),
        "execution_time": datetime.combine(execute, time(9, 30), ET).isoformat(),
        "action": "rebalance" if is_rebalance_day(today, set()) and cutoff.date() == today else "hold",
        "target_holdings": book["holdings"],
        "data_through": str(book.get("as_of")),
        "decided_on": str(book.get("as_of")),
        "regime": book.get("regime"),
        "fallback": f"data server unavailable; frozen book as of {book.get('as_of')}",
    }


def decide(information_cutoff, ds=None, team_id: str | None = None,
           fallback_book: dict | None = None) -> dict:
    """One decision record for the given information cutoff.

    fallback_book: if given and the week's book is not already computed, use it
    instead of computing (the API passes the frozen book when a fresh computation
    would not finish inside the judges' time limit; the record says so)."""
    ds = ds or _dataset(os.environ.get("SV_DATA_ROOT", "."))
    cfg = model.load_config()
    cutoff = _parse_cutoff(information_cutoff)
    days = data.trading_days(ds)
    hol = _holidays(ds) | _closed_inside(days)
    today = last_data_day(cutoff, days)
    decided = week_decision_day(today, days, hol)
    rebalance = decided == today and cutoff.date() == today
    used_fallback = False
    book = _stored(ds, decided, cfg["version"])
    if book is None and fallback_book is not None:
        book, used_fallback = fallback_book, True
    elif book is None:
        book = _compute(ds, decided, cfg)
    decision_time = cutoff + timedelta(minutes=15)  # 16:00 cutoff -> 16:15 decision
    execute = execution_day(decision_time, hol)
    model_id = f"nabla-{cfg['version']}"
    return {
        "schema_version": SCHEMA_VERSION,
        "team_id": team_id or os.environ.get("NABLA_TEAM_ID", "nabla"),
        "model_id": model_id,
        "decision_id": f"{model_id}-{cutoff.date().isoformat()}",
        "information_cutoff": cutoff.isoformat(),
        "decision_time": decision_time.isoformat(),
        "execution_time": datetime.combine(execute, time(9, 30), ET).isoformat(),
        "action": "rebalance" if rebalance else "hold",
        "target_holdings": book["holdings"],
        "data_through": str(today),
        "decided_on": str(decided),
        "regime": book.get("regime"),
        **({"fallback": f"frozen book as of {book.get('as_of')}"} if used_fallback else {}),
    }


def frozen_series(start, end, book: dict, team_id: str | None = None) -> dict:
    """Series when the data server is unreachable: one decision, the frozen book,
    made at its own 16:00 ET cutoff and executed at the window's first weekday
    open, then held. Valid only for a window that starts after the book's data
    (no lookahead); raises ValueError otherwise."""
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    as_of = pd.Timestamp(book["as_of"]).date()
    if start <= as_of:
        raise ValueError(f"frozen book uses data through {as_of}; window starting {start} would look ahead")
    first = start
    while first.weekday() >= 5:
        first += timedelta(days=1)
    if first > end:
        raise ValueError("no weekday in window")
    cfg = model.load_config()
    model_id = f"nabla-{cfg['version']}"
    cutoff = datetime.combine(as_of, CLOSE, ET)
    rec = {
        "schema_version": SCHEMA_VERSION,
        "team_id": team_id or os.environ.get("NABLA_TEAM_ID", "nabla"),
        "model_id": model_id,
        "decision_id": 1,
        "information_cutoff": cutoff.isoformat(),
        "decision_time": (cutoff + timedelta(minutes=15)).isoformat(),
        "execution_time": datetime.combine(first, OPEN, ET).isoformat(),
        "action": "rebalance",
        "target_holdings": book["holdings"],
        "data_through": str(as_of),
        "decided_on": str(as_of),
        "regime": book.get("regime"),
        "fallback": f"data server unavailable; frozen book as of {as_of}, held through the window",
    }
    return {"series": [rec], "model_id": model_id, "start": str(start), "end": str(end),
            "note": "data server unreachable: the frozen book (data through its as_of date) "
                    "bought at the window's first open and held; no lookahead"}


def series_days(start: date, end: date, days: list[date], holidays: set[date]) -> list[date]:
    """Decision days for a window: the last weekly decision before `start` (the
    opening book), then every weekly decision day inside the window whose
    execution (next trading day) still falls on or before `end`."""
    hol = holidays | _closed_inside(days)
    pre = [d for d in days if d < start and is_rebalance_day(d, hol)]
    inside = [d for d in days if start <= d <= end and is_rebalance_day(d, hol)]
    grid = pre[-1:] + inside
    return [d for d in grid if next_trading_day(d, hol) <= end]


def series(start, end, ds=None, team_id: str | None = None, budget_s: float | None = None) -> dict:
    """POST /decisions body for the judges' decision-series rubric
    (starter launchpad/rubric/decisions.yaml): the frozen model replayed week by
    week through [start, end]. Each record is decide() at that day's 16:00 ET
    cutoff, so every book uses only data on or before its own cutoff;
    decision_id counts 1, 2, ... as the format requires.

    budget_s: once the time is spent, weeks not yet computed reuse the latest
    earlier book (older data only, so still point-in-time) and say so in
    "fallback"; the background warmer fills them in for the next call."""
    t0 = _time.time()
    ds = ds or _dataset(os.environ.get("SV_DATA_ROOT", "."))
    start, end = pd.Timestamp(start).date(), pd.Timestamp(end).date()
    days = data.trading_days(ds)
    out, last_book = [], None
    version = model.load_config()["version"]
    for i, d in enumerate(series_days(start, end, days, _holidays(ds)), 1):
        late = budget_s is not None and _time.time() - t0 > budget_s
        stale = last_book if late and _stored(ds, d, version) is None else None
        rec = decide(d, ds=ds, team_id=team_id, fallback_book=stale)
        if stale is not None:
            rec["fallback"] = f"time budget spent: book from {stale.get('as_of')} (earlier data only)"
        last_book = _stored(ds, d, version) or last_book
        rec["decision_id"] = i
        rec["action"] = "rebalance"
        out.append(rec)
    cfg = model.load_config()
    return {"series": out, "model_id": f"nabla-{cfg['version']}", "start": str(start), "end": str(end),
            "note": "weekly decisions (last trading day of each week, 16:00 ET cutoff, next-open execution); "
                    "each book built only from data on or before its information_cutoff"}
