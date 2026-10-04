"""Quality and value from filed fundamentals: point-in-time gating, TTM, definitions."""
import numpy as np
import pandas as pd

from nabla import fundamentals as F

PE = ["2023-06-30", "2023-09-30", "2023-12-31", "2024-03-31"]


def _fund(cols: dict, tickers=("AAA", "BBB")) -> pd.DataFrame:
    rows = []
    for t in tickers:
        for i, pe in enumerate(PE):
            rows.append({"ticker": t, "date": pd.Timestamp(pe), **{k: v[t][i] for k, v in cols.items()}})
    return pd.DataFrame(rows)


def _cal(tickers=("AAA", "BBB"), lag_days=33, accept=None) -> pd.DataFrame:
    rows = []
    for t in tickers:
        for pe in PE:
            fd = pd.Timestamp(pe) + pd.Timedelta(days=lag_days)
            r = {"ticker": t, "filing_date": fd.date()}
            if accept is not None:
                r["acceptance_datetime"] = (fd + pd.Timedelta(hours=accept)).tz_localize("America/New_York")
            rows.append(r)
    return pd.DataFrame(rows)


EPS = {"eps": {"AAA": [1.0, 1.0, 1.0, 1.0], "BBB": [-0.5, -0.5, -0.5, -0.5]}}


def test_resolve_columns_is_case_insensitive():
    m = F.resolve_columns(["Ticker", "DATE", "IS_EPS", "Sales_Rev_Turn"])
    assert m == {"eps": "IS_EPS", "sales": "Sales_Rev_Turn"}


def test_quarter_is_invisible_until_the_day_after_filing():
    f, _ = F.prepare(_fund(EPS), _cal())
    filed = pd.Timestamp(PE[-1]) + pd.Timedelta(days=33)
    before = F.ttm(f, filed + pd.Timedelta(hours=16))       # filing day, 16:00: last quarter not yet known
    after = F.ttm(f, filed + pd.Timedelta(days=1, hours=16))
    assert before.loc["AAA", "last_pe"] == pd.Timestamp(PE[-2])
    assert after.loc["AAA", "last_pe"] == pd.Timestamp(PE[-1])


def test_acceptance_time_is_used_when_present():
    f, _ = F.prepare(_fund(EPS), _cal(accept=10))          # accepted 10:00 ET on the filing day
    filed = pd.Timestamp(PE[-1]) + pd.Timedelta(days=33)
    t = F.ttm(f, filed + pd.Timedelta(hours=16))
    assert t.loc["AAA", "last_pe"] == pd.Timestamp(PE[-1])


def test_unmatched_rows_wait_sixty_days():
    f, _ = F.prepare(_fund(EPS), None)
    assert (f["knowable"] == f["date"] + pd.Timedelta(days=60)).all()


def test_ttm_needs_four_quarters_and_sums_flows():
    f, _ = F.prepare(_fund(EPS), _cal())
    late = pd.Timestamp("2024-12-31")
    t = F.ttm(f, late)
    assert t.loc["AAA", "eps"] == 4.0 and t.loc["BBB", "eps"] == -2.0
    t3 = F.ttm(f[f["date"] > pd.Timestamp(PE[0])], late)      # only three quarters
    assert t3["eps"].isna().all()


def test_value_is_earnings_yield_and_negative_earnings_rank_low():
    f, _ = F.prepare(_fund(EPS), _cal())
    price = pd.Series({"AAA": 40.0, "BBB": 40.0})
    qv, notes = F.quality_value(f, price, pd.Timestamp("2024-12-31"))
    assert notes["value_def"] == "earnings_yield"
    assert np.isclose(qv.loc["AAA", "value"], 0.1) and qv.loc["BBB", "value"] == 0.0


def test_split_inside_the_ttm_window_leaves_value_neutral(monkeypatch):
    monkeypatch.setattr(F, "SPLIT_GUARD", True)
    f, _ = F.prepare(_fund(EPS), _cal())
    price = pd.Series({"AAA": 40.0, "BBB": 40.0})
    splits = pd.DataFrame({"ticker": ["AAA"], "ex_date": [pd.Timestamp("2024-01-15")], "value": [4.0]})
    qv, _ = F.quality_value(f, price, pd.Timestamp("2024-12-31"), splits)
    assert np.isnan(qv.loc["AAA", "value"]) and qv.loc["BBB", "value"] == 0.0


def test_quality_prefers_gross_profit_to_assets():
    cols = {"gross_profit": {"AAA": [10] * 4, "BBB": [5] * 4},
            "total_assets": {"AAA": [100] * 4, "BBB": [100] * 4},
            "net_income": {"AAA": [1] * 4, "BBB": [9] * 4}, "equity": {"AAA": [50] * 4, "BBB": [50] * 4}}
    f, _ = F.prepare(_fund(cols), _cal())
    qv, notes = F.quality_value(f, pd.Series({"AAA": 1.0, "BBB": 1.0}), pd.Timestamp("2024-12-31"))
    assert notes["quality_def"] == "gross_profit_to_assets"
    assert np.isclose(qv.loc["AAA", "quality"], 0.4) and qv.loc["AAA", "quality"] > qv.loc["BBB", "quality"]


def test_quality_falls_back_to_roe_then_margins():
    roe = {"net_income": {"AAA": [2] * 4, "BBB": [1] * 4}, "equity": {"AAA": [40] * 4, "BBB": [-10] * 4}}
    f, _ = F.prepare(_fund(roe), _cal())
    qv, notes = F.quality_value(f, pd.Series({"AAA": 1.0, "BBB": 1.0}), pd.Timestamp("2024-12-31"))
    assert notes["quality_def"] == "roe"
    assert np.isclose(qv.loc["AAA", "quality"], 0.2) and np.isnan(qv.loc["BBB", "quality"])  # negative equity

    margins = {"ebit": {"AAA": [3] * 4, "BBB": [1] * 4}, "sales": {"AAA": [10] * 4, "BBB": [10] * 4},
               "fcf": {"AAA": [2] * 4, "BBB": [1] * 4}}
    f, _ = F.prepare(_fund(margins), _cal())
    qv, notes = F.quality_value(f, pd.Series({"AAA": 1.0, "BBB": 1.0}), pd.Timestamp("2024-12-31"))
    assert notes["quality_def"].startswith("margin_blend")
    assert qv.loc["AAA", "quality"] > qv.loc["BBB", "quality"]


def test_calendar_period_end_match_beats_fallback():
    from nabla import fundamentals as fm
    fund = pd.DataFrame({"ticker": ["A", "A"], "date": pd.to_datetime(["2024-03-31", "2024-06-30"])})
    cal = pd.DataFrame({"ticker": ["A", "A"], "filing_date": pd.to_datetime(["2024-04-25", "2024-07-30"]),
                        "period_end": pd.to_datetime(["2024-03-31", "2024-06-30"])})
    k = fm.knowable_times(fund, cal)
    assert list(k) == list(pd.to_datetime(["2024-04-26", "2024-07-31"]))  # day after filing, not +60d


def test_split_guard_is_off_by_default_because_eps_is_restated():
    f, _ = F.prepare(_fund(EPS), _cal())
    splits = pd.DataFrame({"ticker": ["AAA"], "ex_date": [pd.Timestamp("2024-01-15")], "value": [4.0]})
    qv, _ = F.quality_value(f, pd.Series({"AAA": 40.0, "BBB": 40.0}), pd.Timestamp("2024-12-31"), splits)
    assert np.isclose(qv.loc["AAA", "value"], 0.1)


def test_money_losers_sit_together_at_the_bottom():
    eps = {"eps": {"AAA": [1.0] * 4, "BBB": [-0.1] * 4, "CCC": [-5.0] * 4, "DDD": [0.2] * 4}}
    f, _ = F.prepare(_fund(eps, tickers=("AAA", "BBB", "CCC", "DDD")), _cal(("AAA", "BBB", "CCC", "DDD")))
    qv, _ = F.quality_value(f, pd.Series(40.0, index=["AAA", "BBB", "CCC", "DDD"]), pd.Timestamp("2024-12-31"))
    v = qv["value"]
    assert v["BBB"] == v["CCC"] < v["DDD"] < v["AAA"]


def test_gross_margin_joins_the_quality_blend():
    cols = {"gross_margin": {"AAA": [60.0] * 4, "BBB": [20.0] * 4},
            "ebit": {"AAA": [3] * 4, "BBB": [1] * 4}, "sales": {"AAA": [10] * 4, "BBB": [10] * 4}}
    f, _ = F.prepare(_fund(cols), _cal())
    qv, notes = F.quality_value(f, pd.Series({"AAA": 1.0, "BBB": 1.0}), pd.Timestamp("2024-12-31"))
    assert "gross_margin" in notes["quality_def"] and qv.loc["AAA", "quality"] > qv.loc["BBB", "quality"]
