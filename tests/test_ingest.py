"""Bloomberg ingest against a fake Terminal: layout, idempotence, point-in-time dates."""
from datetime import date

import numpy as np
import pandas as pd

from nabla import fundamentals, ingest, store


class FakeTerminal:
    def history(self, tickers, fields, start, end, periodicity="DAILY", **kw):
        days = pd.bdate_range(start, end) if periodicity == "DAILY" else pd.to_datetime(["2024-03-31", "2024-06-30"])
        rows = []
        for t in tickers:
            for i, d in enumerate(days):
                r = {"security": t if " " in t else f"{t} US Equity", "date": d.date()}
                for f in fields:
                    r[f] = {"ANNOUNCEMENT_DT": (d + pd.Timedelta(days=30)).date()}.get(f, 100.0 + i)
                rows.append(r)
        return pd.DataFrame(rows)


def test_run_builds_a_store_the_model_can_read(tmp_path):
    t = FakeTerminal()
    info = ingest.run(t, ["AAPL", "BRK.B"], date(2024, 1, 2), date(2024, 7, 1), tmp_path, log=lambda *_: None)
    st = store.Store(tmp_path)
    assert st.universe() == ["AAPL", "BRK.B"]
    days = st.trading_days()
    assert days[-1] == date(2024, 7, 1) and info["last_day"] == "2024-07-01"
    sv = st.state_vector()
    assert {"atm_iv", "days_to_next_report", "guidance_range_velocity"} <= set(sv.columns)
    assert sv["guidance_range_velocity"].isna().all()
    assert st.benchmark("SPX")["close"].notna().all()

    # a second pull of the same window changes nothing
    n = len(st.get("stocks_daily"))
    ingest.run(t, ["AAPL", "BRK.B"], date(2024, 1, 2), date(2024, 7, 1), tmp_path, log=lambda *_: None)
    assert len(store.Store(tmp_path).get("stocks_daily")) == n


def test_quarter_is_knowable_only_after_its_announcement(tmp_path):
    ingest.run(FakeTerminal(), ["AAPL"], date(2024, 1, 2), date(2024, 7, 1), tmp_path, log=lambda *_: None)
    st = store.Store(tmp_path)
    f, _ = fundamentals.prepare(st.get("fundamentals_actuals"), st.structural("report_calendar_us"))
    q1 = f[f["date"] == pd.Timestamp("2024-03-31")].iloc[0]
    assert q1["knowable"] == pd.Timestamp("2024-04-30") + pd.Timedelta(days=1)  # announced Apr 30


def test_days_to_next_report():
    dates = pd.DataFrame({"ticker": ["A", "A", "A"], "date": pd.to_datetime(["2024-04-01", "2024-04-30", "2024-05-02"])})
    cal = pd.DataFrame({"ticker": ["A"], "filing_date": pd.to_datetime(["2024-04-30"])})
    out = ingest.days_to_next_report(dates, cal)
    assert out.iloc[0] == 29 and out.iloc[1] == 0 and np.isnan(out.iloc[2])
