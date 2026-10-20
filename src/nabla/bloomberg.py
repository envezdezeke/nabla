"""Bloomberg Terminal connector (Desktop API, research and monitoring only).

Talks to the local Terminal through blpapi on localhost:8194, so it only works
on a machine where the Terminal is logged in. It is NOT used by decide(): the
judges replay the frozen model from their own data, and a Terminal feed cannot
be replayed. Every pull is stamped with the wall-clock time it was taken and
written to artifacts/bbg/, so anything built on it can be audited as of that
time. Bloomberg Intelligence and research reports are not exposed by the
Desktop API; only market data, reference data and news requests are.

blpapi is not on PyPI. Install from Bloomberg's index:
    pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple blpapi
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

OUT = Path(__file__).resolve().parents[2] / "artifacts" / "bbg"
REFDATA = "//blp/refdata"
MKTDATA = "//blp/mktdata"


def security(ticker: str) -> str:
    """'AAPL' -> 'AAPL US Equity'; names already carrying a yellow key pass through."""
    t = ticker.strip()
    return t if " " in t else f"{t.replace('.', '/')} US Equity"


class BloombergError(RuntimeError):
    pass


def _blpapi():
    try:
        import blpapi
    except ImportError as e:
        raise BloombergError("blpapi is not installed (see module docstring)") from e
    return blpapi


class Terminal:
    """One blpapi session. `session` can be injected for tests."""

    def __init__(self, host: str = "localhost", port: int = 8194, session=None):
        if session is None:
            blpapi = _blpapi()
            opts = blpapi.SessionOptions()
            opts.setServerHost(host)
            opts.setServerPort(port)
            session = blpapi.Session(opts)
            if not session.start():
                raise BloombergError(f"cannot reach the Terminal at {host}:{port}; is it logged in?")
        self.session = session
        self._services: set[str] = set()

    def _service(self, name: str):
        if name not in self._services:
            if not self.session.openService(name):
                raise BloombergError(f"cannot open {name}")
            self._services.add(name)
        return self.session.getService(name)

    def _send(self, req) -> list:
        """Send a request and collect every message of its response."""
        blpapi = _blpapi()
        self.session.sendRequest(req)
        msgs = []
        while True:
            ev = self.session.nextEvent(5000)
            for m in ev:
                if str(m.messageType()) in ("SessionTerminated", "ServiceOpenFailure"):
                    raise BloombergError(str(m))
                msgs.append(m)
            if ev.eventType() == blpapi.Event.RESPONSE:
                return msgs
            if ev.eventType() == blpapi.Event.TIMEOUT:
                raise BloombergError("timed out waiting for the Terminal")

    def reference(self, tickers: list[str], fields: list[str], overrides: dict | None = None) -> pd.DataFrame:
        """Current (or overridden) values: one row per ticker, one column per field."""
        req = self._service(REFDATA).createRequest("ReferenceDataRequest")
        for t in tickers:
            req.getElement("securities").appendValue(security(t))
        for f in fields:
            req.getElement("fields").appendValue(f)
        for k, v in (overrides or {}).items():
            o = req.getElement("overrides").appendElement()
            o.setElement("fieldId", k)
            o.setElement("value", str(v))
        rows = {}
        for m in self._send(req):
            if not m.hasElement("securityData"):
                continue
            for sd in m.getElement("securityData").values():
                rows[sd.getElementAsString("security")] = _flat(sd.getElement("fieldData"))
        return _stamp(pd.DataFrame.from_dict(rows, orient="index").rename_axis("security"))

    def history(self, tickers: list[str], fields: list[str], start: date, end: date,
                adjust_splits: bool = True, periodicity: str = "DAILY") -> pd.DataFrame:
        """History, long format: security, date, one column per field.
        periodicity QUARTERLY gives fiscal-quarter rows (dated at period end) for fundamentals."""
        req = self._service(REFDATA).createRequest("HistoricalDataRequest")
        for t in tickers:
            req.getElement("securities").appendValue(security(t))
        for f in fields:
            req.getElement("fields").appendValue(f)
        req.set("startDate", start.strftime("%Y%m%d"))
        req.set("endDate", end.strftime("%Y%m%d"))
        req.set("periodicitySelection", periodicity)
        if periodicity != "DAILY":
            req.set("periodicityAdjustment", "FISCAL")
        req.set("adjustmentSplit", adjust_splits)
        req.set("adjustmentNormal", False)
        req.set("adjustmentAbnormal", False)
        rows = []
        for m in self._send(req):
            if not m.hasElement("securityData"):
                continue
            sd = m.getElement("securityData")
            sec = sd.getElementAsString("security")
            for fd in sd.getElement("fieldData").values():
                rows.append({"security": sec, **_flat(fd)})
        return _stamp(pd.DataFrame(rows))

    def intraday(self, ticker: str, start: datetime, end: datetime, interval: int = 1,
                 event: str = "TRADE") -> pd.DataFrame:
        """Minute bars (UTC timestamps); the Terminal keeps only the recent past."""
        req = self._service(REFDATA).createRequest("IntradayBarRequest")
        req.set("security", security(ticker))
        req.set("eventType", event)
        req.set("interval", interval)
        req.set("startDateTime", start)
        req.set("endDateTime", end)
        rows = []
        for m in self._send(req):
            if m.hasElement("barData"):
                rows += [_flat(b) for b in m.getElement("barData").getElement("barTickData").values()]
        return _stamp(pd.DataFrame(rows))

    def snapshot(self, tickers: list[str], fields=("LAST_PRICE", "BID", "ASK", "VOLUME"),
                 seconds: float = 3.0) -> pd.DataFrame:
        """Live quotes: subscribe, keep the latest value per field for `seconds`, unsubscribe."""
        blpapi = _blpapi()
        self._service(MKTDATA)
        subs = blpapi.SubscriptionList()
        for i, t in enumerate(tickers):
            subs.add(security(t), list(fields), "", blpapi.CorrelationId(i))
        self.session.subscribe(subs)
        latest: dict[int, dict] = {}
        stop = time.time() + seconds
        try:
            while time.time() < stop:
                ev = self.session.nextEvent(500)
                if ev.eventType() == blpapi.Event.SUBSCRIPTION_DATA:
                    for m in ev:
                        latest.setdefault(m.correlationIds()[0].value(), {}).update(_flat(m.asElement()))
        finally:
            self.session.unsubscribe(subs)
        rows = {security(tickers[i]): {f: v.get(f) for f in fields} for i, v in latest.items()}
        return _stamp(pd.DataFrame.from_dict(rows, orient="index").rename_axis("security"))

    def close(self):
        self.session.stop()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _flat(el) -> dict:
    """Scalar sub-elements of a blpapi element as a dict; nested/bulk fields are skipped."""
    out = {}
    for i in range(el.numElements()):
        c = el.getElement(i)
        if not c.isComplexType() and not c.isArray():
            out[str(c.name())] = c.getValue()
    return out


def _stamp(df: pd.DataFrame) -> pd.DataFrame:
    df.attrs["pulled_at"] = datetime.now(timezone.utc).isoformat()
    return df


def save(df: pd.DataFrame, name: str) -> Path:
    """Write a pull to artifacts/bbg/<name>_<utc time>.parquet with its pull time in a sidecar."""
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    f = OUT / f"{name}_{stamp}.parquet"
    df.to_parquet(f)
    f.with_suffix(".json").write_text(json.dumps({"pulled_at": df.attrs.get("pulled_at"), "rows": len(df)}))
    return f
