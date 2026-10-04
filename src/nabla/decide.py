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

import os
from datetime import date, datetime, time, timedelta
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


def _dataset(root: str):
    from statevector import Dataset
    if root not in _DS:
        _DS[root] = Dataset(root)
    return _DS[root]


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
    key = (id(ds), decided, cfg["version"])
    used_fallback = False
    if key in _BOOKS:
        book = _BOOKS[key]
    elif fallback_book is not None:
        book, used_fallback = fallback_book, True
    else:
        _BOOKS[key] = live.build_book(ds, cfg, asof=decided)
        book = _BOOKS[key]
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
