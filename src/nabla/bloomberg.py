"""Bloomberg Desktop API access with an on-disk cache (docs/BLOOMBERG_RULES.md).

Everything pulled from Bloomberg is written under artifacts/bbg/, which is
gitignored and never leaves the terminal machine. Nothing in this module prints
data: it reports counts only.

  * `Terminal`     one blpapi session to localhost:8194 (the logged-in terminal).
  * `Budget`       daily hit ledger (artifacts/bbg/usage.json). A pull that would
                   pass the limit stops before it is sent, so it can resume tomorrow.
  * `Cache`        long tables per field plus a coverage ledger: a (ticker, field)
                   range that was requested once is never requested again.
  * `BbgDataset`   the slice of the statevector `Dataset` API the model reads
                   (universe, prices, fundamentals, SPX, state vector), served from
                   the cache, so `live.build_book` and `decide.decide` run unchanged.

Substitutes for the statevector-only inputs (see `BbgDataset.state_vector`):
  guidance_range_velocity -> 20-trading-day change in the consensus EPS estimate
                             (BEST_EPS, blended forward 12 months) divided by price
  days_to_next_report     -> next announcement date from ANNOUNCEMENT_DT history
                             and EXPECTED_REPORT_DT
  atm_iv, log_fv_gap      -> not pulled (vol_premium has weight 0; value uses filed EPS)
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import polars as pl

ROOT = Path(__file__).resolve().parents[2]
BBG_DIR = ROOT / "artifacts" / "bbg"
ET = ZoneInfo("America/New_York")
HOST, PORT = "localhost", 8194

INDEX_SPX = "SPX Index"
PRICE_FIELDS = ["PX_LAST", "PX_VOLUME"]
EST_FIELD, EST_OVERRIDE = "BEST_EPS", {"BEST_FPERIOD_OVERRIDE": "1BF"}
# quarterly fundamentals the model reads (quality = margin blend, value = EPS yield);
# total assets and equity are left out on purpose so quality keeps its v1.4 definition
FUND_FIELDS = ["IS_EPS", "SALES_REV_TURN", "GROSS_PROFIT", "IS_OPER_INC", "NET_INCOME",
               "CF_FREE_CASH_FLOW", "EBITDA", "NET_DEBT", "GROSS_MARGIN"]
FUND_START = date(2022, 1, 1)  # SUE needs 4 + 8 prior quarters
HISTORY_START = date(2018, 1, 1)  # the backtest start; SPX regime percentiles use it

DATE_FIELDS = ("ANNOUNCEMENT_DT",)
BATCH = 40  # securities per request


class BudgetExceeded(RuntimeError):
    pass


# ---------------------------------------------------------------- tickers

def to_bbg(ticker: str) -> str:
    return ticker if ticker.endswith(("Index", "Equity")) else f"{ticker.replace('.', '/')} US Equity"


def from_bbg(security: str) -> str:
    return security.rsplit(" ", 2)[0].replace("/", ".") if security.endswith("Equity") else security


def last_completed_day(now: datetime | None = None) -> date:
    """Newest weekday whose close is final (today only after 16:30 ET)."""
    now = now or datetime.now(ET)
    d = now.date() if now.time() >= datetime.strptime("16:30", "%H:%M").time() else now.date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


# ---------------------------------------------------------------- budget

class Budget:
    """Hits per calendar day. One hit = one value of one field for one security."""

    def __init__(self, limit: int | None = None):
        raw = str(limit or os.environ.get("NABLA_BBG_DAILY_HITS", "500000"))
        digits = "".join(c for c in raw if c.isdigit())  # tolerate "<10000>" or "500,000"
        self.limit = int(digits) if digits else 500_000
        self.path = BBG_DIR / "usage.json"

    def _read(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def used(self) -> int:
        return int(self._read().get(date.today().isoformat(), 0))

    def remaining(self) -> int:
        return max(0, self.limit - self.used())

    def check(self, planned: int) -> None:
        if planned > self.remaining():
            raise BudgetExceeded(f"{planned:,} hits planned, {self.remaining():,} left today "
                                 f"(limit {self.limit:,}; set NABLA_BBG_DAILY_HITS to change)")

    def add(self, hits: int) -> None:
        BBG_DIR.mkdir(parents=True, exist_ok=True)
        u = self._read()
        k = date.today().isoformat()
        u[k] = int(u.get(k, 0)) + int(hits)
        self.path.write_text(json.dumps(u, indent=1))


# ---------------------------------------------------------------- terminal

class Terminal:
    """blpapi session to the logged-in terminal. Use as a context manager."""

    def __init__(self, budget: Budget | None = None):
        self.budget = budget or Budget()
        self.session = None
        self.service = None

    def __enter__(self):
        import blpapi
        self._b = blpapi
        o = blpapi.SessionOptions()
        o.setServerHost(HOST)
        o.setServerPort(PORT)
        self.session = blpapi.Session(o)
        if not self.session.start() or not self.session.openService("//blp/refdata"):
            raise ConnectionError("cannot reach the Bloomberg terminal on localhost:8194 (is it logged in?)")
        self.service = self.session.getService("//blp/refdata")
        return self

    def __exit__(self, *exc):
        if self.session is not None:
            self.session.stop()

    def _messages(self, req):
        self.session.sendRequest(req)
        idle = 0
        while True:
            ev = self.session.nextEvent(500)
            if ev.eventType() == self._b.Event.TIMEOUT:
                idle += 1
                if idle > 240:
                    raise TimeoutError("no response from the terminal for 2 minutes")
                continue
            idle = 0
            if ev.eventType() in (self._b.Event.PARTIAL_RESPONSE, self._b.Event.RESPONSE):
                yield from ev
            if ev.eventType() == self._b.Event.RESPONSE:
                return

    @staticmethod
    def _set(req, name: str, values) -> None:
        for v in values:
            req.append(name, v)

    def history(self, securities: list[str], fields: list[str], start: date, end: date,
                periodicity: str = "DAILY", overrides: dict | None = None) -> tuple[pd.DataFrame, dict]:
        """Long frame security, date, field, value; and notes (bad securities / fields)."""
        planned = len(securities) * len(fields) * max(1, int((end - start).days * (5 / 7))) \
            if periodicity == "DAILY" else len(securities) * len(fields) * max(1, (end - start).days // 90 + 1)
        self.budget.check(planned)
        req = self.service.createRequest("HistoricalDataRequest")
        self._set(req, "securities", securities)
        self._set(req, "fields", fields)
        req.set("startDate", start.strftime("%Y%m%d"))
        req.set("endDate", end.strftime("%Y%m%d"))
        req.set("periodicitySelection", periodicity)
        req.set("adjustmentSplit", True)
        req.set("adjustmentNormal", False)
        req.set("adjustmentAbnormal", False)
        for k, v in (overrides or {}).items():
            o = req.getElement("overrides").appendElement()
            o.setElement("fieldId", k)
            o.setElement("value", v)
        rows, bad_sec, bad_fld = [], [], set()
        for msg in self._messages(req):
            if not msg.hasElement("securityData"):
                continue
            sd = msg.getElement("securityData")
            sec = sd.getElementAsString("security")
            if sd.hasElement("securityError"):
                bad_sec.append(sec)
                continue
            for i in range(sd.getElement("fieldExceptions").numValues()):
                bad_fld.add(sd.getElement("fieldExceptions").getValueAsElement(i).getElementAsString("fieldId"))
            fd = sd.getElement("fieldData")
            for i in range(fd.numValues()):
                pt = fd.getValueAsElement(i)
                d = pt.getElementAsDatetime("date")
                for f in fields:
                    if pt.hasElement(f):
                        rows.append((sec, d, f, pt.getElement(f).getValue()))
        df = pd.DataFrame(rows, columns=["security", "date", "field", "value"])
        self.budget.add(len(df))
        return df, {"bad_securities": bad_sec, "bad_fields": sorted(bad_fld), "hits": len(df)}

    def reference(self, securities: list[str], fields: list[str], overrides: dict | None = None,
                  bulk: bool = False) -> tuple[pd.DataFrame, dict]:
        """Current values (BDP); with bulk=True each field is a table, returned flattened."""
        self.budget.check(len(securities) * len(fields))
        req = self.service.createRequest("ReferenceDataRequest")
        self._set(req, "securities", securities)
        self._set(req, "fields", fields)
        for k, v in (overrides or {}).items():
            o = req.getElement("overrides").appendElement()
            o.setElement("fieldId", k)
            o.setElement("value", v)
        rows, bad_sec = [], []
        for msg in self._messages(req):
            if not msg.hasElement("securityData"):
                continue
            arr = msg.getElement("securityData")
            for i in range(arr.numValues()):
                sd = arr.getValueAsElement(i)
                sec = sd.getElementAsString("security")
                if sd.hasElement("securityError"):
                    bad_sec.append(sec)
                    continue
                fd = sd.getElement("fieldData")
                for f in fields:
                    if not fd.hasElement(f):
                        continue
                    el = fd.getElement(f)
                    if bulk:
                        for j in range(el.numValues()):
                            row = el.getValueAsElement(j)
                            rows.append((sec, f, row.getElement(0).getValue()))
                    else:
                        rows.append((sec, f, el.getValue()))
        df = pd.DataFrame(rows, columns=["security", "field", "value"])
        self.budget.add(len(df))
        return df, {"bad_securities": bad_sec, "hits": len(df)}


# ---------------------------------------------------------------- cache

class Cache:
    """Per-field long tables (ticker, date, value) and the ranges already requested."""

    def __init__(self, directory: Path = BBG_DIR):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cov_path = self.dir / "coverage.json"

    @staticmethod
    def _key(field: str, overrides: dict | None) -> str:
        suffix = "@" + ",".join(f"{v}" for _, v in sorted((overrides or {}).items())) if overrides else ""
        return field + suffix

    def _file(self, key: str) -> Path:
        return self.dir / f"hist_{key.replace('@', '_at_').replace('/', '_')}.parquet"

    def coverage(self) -> dict:
        return json.loads(self.cov_path.read_text()) if self.cov_path.exists() else {}

    def read(self, field: str, overrides: dict | None = None) -> pd.DataFrame:
        f = self._file(self._key(field, overrides))
        return pd.read_parquet(f) if f.exists() else pd.DataFrame(columns=["ticker", "date", "value"])

    def write(self, field: str, new: pd.DataFrame, overrides: dict | None = None) -> None:
        f = self._file(self._key(field, overrides))
        old = pd.read_parquet(f) if f.exists() else new.iloc[0:0]
        both = pd.concat([old, new], ignore_index=True).drop_duplicates(["ticker", "date"], keep="last")
        both.to_parquet(f)

    def mark(self, key: str, tickers: list[str], start: date, end: date) -> None:
        cov = self.coverage()
        slot = cov.setdefault(key, {})
        for t in tickers:
            lo, hi = slot.get(t, [start.isoformat(), end.isoformat()])
            slot[t] = [min(lo, start.isoformat()), max(hi, end.isoformat())]
        self.cov_path.write_text(json.dumps(cov))

    def missing(self, key: str, tickers: list[str], start: date, end: date) -> dict[tuple[date, date], list[str]]:
        """Group tickers by the date range still to request."""
        slot = self.coverage().get(key, {})
        out: dict[tuple[date, date], list[str]] = {}
        for t in tickers:
            if t not in slot:
                ranges = [(start, end)]
            else:
                lo, hi = date.fromisoformat(slot[t][0]), date.fromisoformat(slot[t][1])
                ranges = []
                if start < lo:
                    ranges.append((start, lo - timedelta(days=1)))
                if end > hi:
                    ranges.append((hi + timedelta(days=1), end))
            for r in ranges:
                out.setdefault(r, []).append(t)
        return out


def plan_history(cache: Cache, tickers: list[str], fields: list[str], start: date, end: date,
                 overrides: dict | None = None, periodicity: str = "DAILY") -> int:
    """Hits a pull would cost (an estimate from the missing ranges); requests nothing."""
    total = 0
    for f in fields:
        for (a, b), ts in cache.missing(cache._key(f, overrides), tickers, start, end).items():
            n = max(1, int((b - a).days * 5 / 7)) if periodicity == "DAILY" else max(1, (b - a).days // 90 + 1)
            total += len(ts) * n
    return total


def pull_history(term: Terminal, cache: Cache, tickers: list[str], fields: list[str], start: date, end: date,
                 overrides: dict | None = None, periodicity: str = "DAILY") -> dict:
    """Request only what the cache lacks, one field at a time, and cache every batch."""
    notes = {"hits": 0, "requests": 0, "bad_securities": set(), "bad_fields": set(), "stopped": None}
    for f in fields:
        key = cache._key(f, overrides)
        for (a, b), ts in cache.missing(key, tickers, start, end).items():
            for i in range(0, len(ts), BATCH):
                chunk = ts[i:i + BATCH]
                try:
                    df, n = term.history([to_bbg(t) for t in chunk], [f], a, b, periodicity, overrides)
                except BudgetExceeded as e:
                    notes["stopped"] = str(e)
                    return notes
                notes["requests"] += 1
                notes["hits"] += n["hits"]
                notes["bad_securities"] |= {from_bbg(s) for s in n["bad_securities"]}
                notes["bad_fields"] |= set(n["bad_fields"])
                if len(df):
                    new = pd.DataFrame({"ticker": df["security"].map(from_bbg),
                                        "date": pd.to_datetime(df["date"]),
                                        "value": pd.to_numeric(df["value"], errors="coerce")
                                        if f not in DATE_FIELDS else pd.to_datetime(df["value"], errors="coerce")})
                    cache.write(f, new, overrides)
                cache.mark(key, [t for t in chunk if t not in notes["bad_securities"]], a, b)
    return notes


# ---------------------------------------------------------------- dataset

class BbgDataset:
    """The parts of the statevector `Dataset` the model reads, served from the cache."""

    base = None  # not a remote dataset: loaders skip the yearly download cache

    def __init__(self, directory: Path = BBG_DIR, universe: list[str] | None = None):
        self.cache = Cache(directory)
        self._universe = universe

    # -- universe and calendar
    def universe(self) -> list[str]:
        if self._universe is None:
            f = self.cache.dir / "universe.json"
            if not f.exists():
                raise FileNotFoundError("no cached universe; run scripts/bbg_pull.py first")
            self._universe = json.loads(f.read_text())["tickers"]
        return list(self._universe)

    def _wide(self, field: str, overrides: dict | None = None) -> pd.DataFrame:
        df = self.cache.read(field, overrides)
        return df.pivot_table(index="date", columns="ticker", values="value", aggfunc="last").sort_index()

    def trading_days(self) -> list[date]:
        spx = self.cache.read("PX_LAST")
        spx = spx[spx["ticker"] == INDEX_SPX]
        if spx.empty:
            raise FileNotFoundError("no SPX history cached yet; finish scripts/bbg_pull.py --run first")
        return sorted(d.date() for d in pd.to_datetime(spx["date"]).unique())

    def holidays(self):
        raise NotImplementedError  # decide._holidays falls back to gaps in the data

    # -- panels
    def get(self, name: str, start=None, end=None, limit=None, lazy: bool = False):
        if name == "stocks_daily":
            px = self.cache.read("PX_LAST").rename(columns={"value": "close"})
            vol = self.cache.read("PX_VOLUME").rename(columns={"value": "volume"})
            df = px.merge(vol, on=["ticker", "date"], how="left")
            df = df[df["ticker"].isin(self.universe())]
            if start is not None:
                df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))]
            out = pl.from_pandas(df.assign(date=df["date"].dt.date).reset_index(drop=True))
            return out.lazy() if lazy else out.to_pandas()
        if name == "fundamentals_actuals":
            return self._fundamentals()
        if name == "reference_tickers":
            return pd.DataFrame({"ticker": self.universe()})  # no SIC codes: clusters give the groups
        raise KeyError(name)

    def _fundamentals(self) -> pd.DataFrame:
        frames = []
        for f in FUND_FIELDS:
            d = self.cache.read(f)
            if len(d):
                frames.append(d.rename(columns={"value": f.lower()}).set_index(["ticker", "date"]))
        if not frames:
            raise KeyError("no fundamentals cached")
        return pd.concat(frames, axis=1).reset_index()

    def _announcements(self) -> pd.DataFrame:
        a = self.cache.read("ANNOUNCEMENT_DT")
        if a.empty:
            return pd.DataFrame(columns=["ticker", "period_end", "filing_date"])
        out = a.rename(columns={"date": "period_end"})
        out["filing_date"] = pd.to_datetime(out["value"])
        return out[["ticker", "period_end", "filing_date"]].dropna()

    def _scan(self, name: str):
        if name == "report_calendar_us":
            return pl.from_pandas(self._announcements().assign(
                period_end=lambda d: d["period_end"].dt.date, filing_date=lambda d: d["filing_date"].dt.date)).lazy()
        raise KeyError(name)

    def structural(self, name: str) -> pd.DataFrame:
        if name == "corporate_actions":  # prices are pulled split-adjusted
            return pd.DataFrame(columns=["ticker", "ex_date", "kind", "value"])
        raise KeyError(name)

    def benchmark(self, name: str) -> pd.DataFrame:
        if name != "SPX":
            raise KeyError(name)
        spx = self.cache.read("PX_LAST")
        spx = spx[spx["ticker"] == INDEX_SPX].sort_values("date")
        return pd.DataFrame({"date": spx["date"].values, "close": spx["value"].values})

    def state_vector(self, start=None, end=None, lazy: bool = False):
        """guidance_range_velocity and days_to_next_report per ticker and trading day."""
        close = self._wide("PX_LAST")
        close = close[[c for c in close.columns if c in set(self.universe())]]
        est = self._wide(EST_FIELD, EST_OVERRIDE).reindex(close.index).ffill(limit=5)
        est = est.reindex(columns=close.columns)
        gv = (est - est.shift(20)) / close
        ann = self._announcements()
        dtr = pd.DataFrame(np.nan, index=close.index, columns=close.columns)
        if len(ann):
            exp = self.cache.read("EXPECTED_REPORT_DT")
            future = pd.concat([ann[["ticker", "filing_date"]],
                                pd.DataFrame({"ticker": exp["ticker"],
                                              "filing_date": pd.to_datetime(exp["value"], errors="coerce")})]
                               if len(exp) else [ann[["ticker", "filing_date"]]]).dropna()
            by = {t: np.sort(g["filing_date"].values) for t, g in future.groupby("ticker")}
            idx = close.index.values
            for t, arr in by.items():
                if t in dtr.columns:
                    pos = np.searchsorted(arr, idx, side="right")
                    nxt = np.where(pos < len(arr), arr[np.minimum(pos, len(arr) - 1)], np.datetime64("NaT"))
                    dtr[t] = (nxt - idx) / np.timedelta64(1, "D")
        if start is not None:
            close_idx = close.index[(close.index >= pd.Timestamp(start)) & (close.index <= pd.Timestamp(end))]
        else:
            close_idx = close.index
        long = pd.DataFrame({
            "guidance_range_velocity": gv.loc[close_idx].stack(),
            "days_to_next_report": dtr.loc[close_idx].stack(),
        }).rename_axis(["date", "ticker"]).reset_index()
        out = pl.from_pandas(long.assign(date=long["date"].dt.date))
        return out.lazy() if lazy else out.to_pandas()
