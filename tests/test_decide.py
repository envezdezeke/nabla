from datetime import date

import pandas as pd

from nabla import decide as dc


def test_calendar_helpers():
    hol = {date(2024, 12, 25)}
    assert dc.next_trading_day(date(2024, 12, 24), hol) == date(2024, 12, 26)
    assert dc.next_trading_day(date(2024, 6, 7), set()) == date(2024, 6, 10)  # Fri -> Mon
    assert dc.is_rebalance_day(date(2024, 6, 7), set())                      # Friday
    assert not dc.is_rebalance_day(date(2024, 6, 6), set())
    # Good Friday style: Thursday is the last session of the week
    assert dc.is_rebalance_day(date(2024, 3, 28), {date(2024, 3, 29)})


def test_cutoff_parsing_and_last_data_day():
    c = dc._parse_cutoff("2024-06-05")
    assert c.hour == 16 and str(c.tzinfo) == "America/New_York"
    days = [date(2024, 6, 3), date(2024, 6, 4), date(2024, 6, 5)]
    assert dc.last_data_day(dc._parse_cutoff("2024-06-05T16:00:00-04:00"), days) == date(2024, 6, 5)
    assert dc.last_data_day(dc._parse_cutoff("2024-06-05T10:00:00-04:00"), days) == date(2024, 6, 4)


def test_decision_record(ds):
    days = [d for d in ds.trading_days()]
    fri = max(d for d in days if pd.Timestamp(d).weekday() == 4 and d < days[-1])
    rec = dc.decide(fri, ds=ds)
    for k in ("schema_version", "team_id", "model_id", "decision_id", "information_cutoff",
              "decision_time", "execution_time", "action", "target_holdings"):
        assert k in rec
    assert rec["action"] == "rebalance" and rec["data_through"] == str(fri)
    w = [h["weight"] for h in rec["target_holdings"]]
    assert abs(sum(w) - 1) < 1e-6 and min(w) >= 0
    assert rec["execution_time"].startswith(str(dc.next_trading_day(fri, set())))
    # midweek: hold, same target as the previous Friday's decision
    wed = pd.Timestamp(fri) + pd.Timedelta(days=5)
    if wed.date() in days:
        rec2 = dc.decide(wed.date(), ds=ds)
        assert rec2["action"] == "hold" and rec2["target_holdings"] == rec["target_holdings"]


def test_decision_ignores_later_data(ds, tmp_path):
    """Same cutoff, data truncated after it: identical record (no lookahead)."""
    import polars as pl
    from statevector import Dataset
    import shutil
    root = tmp_path / "trunc"
    shutil.copytree(ds.root, root)
    cut = date(2025, 6, 6)
    for f in ["data/canonical/stocks_daily.parquet", "data/canonical/state_vector.parquet",
              "data/canonical/index_daily.parquet"]:
        df = pl.read_parquet(root / f)
        df.filter(pl.col("date") <= cut).write_parquet(root / f)
    a = dc.decide(cut, ds=ds)
    b = dc.decide(cut, ds=Dataset(str(root)))
    assert a["target_holdings"] == b["target_holdings"]


def test_closed_weekdays_inside_data_are_holidays():
    days = [date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 8)]  # Labor Day 9/7 missing
    hol = dc._closed_inside(days)
    assert date(2026, 9, 7) in hol
    assert dc.next_trading_day(date(2026, 9, 4), hol) == date(2026, 9, 8)


def test_execution_is_after_the_decision():
    hol = set()
    fri_close = dc._parse_cutoff("2024-06-07")                    # Fri 16:00 -> Mon open
    assert dc.execution_day(fri_close + pd.Timedelta(minutes=15), hol) == date(2024, 6, 10)
    wed_10 = dc._parse_cutoff("2024-06-05T10:00:00-04:00")        # after the open -> Thu
    assert dc.execution_day(wed_10 + pd.Timedelta(minutes=15), hol) == date(2024, 6, 6)
    wed_8 = dc._parse_cutoff("2024-06-05T08:00:00-04:00")         # before the open -> same day
    assert dc.execution_day(wed_8 + pd.Timedelta(minutes=15), hol) == date(2024, 6, 5)


def test_series_grid_and_records(ds):
    from statevector.backtest import validate_decision_series
    days = list(ds.trading_days())
    end = days[-1]
    start = (pd.Timestamp(end) - pd.Timedelta(days=28)).date()
    body = dc.series(start, end, ds=ds)
    recs = body["series"]
    assert [r["decision_id"] for r in recs] == list(range(1, len(recs) + 1))
    assert recs[0]["information_cutoff"] < str(start)            # opening book before the window
    decisions, errors = validate_decision_series(recs)
    assert not errors, errors
    assert len(decisions) == len(recs) >= 4


def test_series_time_budget_reuses_earlier_books_only(ds):
    from statevector.backtest import validate_decision_series
    dc._BOOKS.clear()
    days = list(ds.trading_days())
    end = days[-1]
    start = (pd.Timestamp(end) - pd.Timedelta(days=28)).date()
    recs = dc.series(start, end, ds=ds, budget_s=0)["series"]
    assert "fallback" not in recs[0] and all("fallback" in r for r in recs[1:])
    assert all(r["target_holdings"] == recs[0]["target_holdings"] for r in recs[1:])  # older book, no lookahead
    assert not validate_decision_series(recs)[1]
