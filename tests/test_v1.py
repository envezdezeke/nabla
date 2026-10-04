import numpy as np
import pandas as pd
import pytest

from nabla import book, combine, data, model, pipeline, sim


def test_split_adjust_only_where_raw_jump_exists():
    idx = pd.bdate_range("2024-01-01", periods=6)
    raw = pd.DataFrame({"A": [100, 101, 102, 25.5, 26, 26.5], "B": [50, 51, 52, 53, 54, 55.0]}, index=idx)
    vol = pd.DataFrame(1.0, index=idx, columns=raw.columns)
    splits = pd.DataFrame({"ticker": ["A", "B"], "ex_date": [idx[3], idx[3]], "value": [4.0, 2.0]})
    c, v, notes = data.split_adjust(raw, vol, splits)
    assert notes == {"splits_applied": 1, "splits_already_adjusted": 1}
    assert c["A"].iloc[2] == pytest.approx(25.5) and v["A"].iloc[0] == 4.0
    pd.testing.assert_series_equal(c["B"], raw["B"])  # B never jumped: left alone


def test_composite_does_not_favor_missing_factors():
    ft = pd.DataFrame({"f1": np.linspace(-1, 1, 20), "f2": np.linspace(-1, 1, 20)},
                      index=[f"T{i}" for i in range(20)])
    ft.loc["T19", "f2"] = np.nan  # best on f1, missing f2
    s = combine.composite(ft, pd.Series("g", index=ft.index), {"f1": 1.0, "f2": 1.0})
    assert s["T19"] < s["T18"]  # missing counts as neutral, not as "average of what's there"


def test_bands_and_sector_cap():
    names = [f"T{i}" for i in range(40)]
    score = pd.Series(np.arange(40, 0, -1.0), index=names)  # T0 best
    groups = pd.Series(["a"] * 10 + [f"g{i}" for i in range(30)], index=names)
    picks = book.select(score, groups, held=["T25", "T35"], n=15, exit_rank=30)
    assert "T25" in picks and "T35" not in picks  # rank 26 stays, rank 36 exits
    assert sum(groups[p] == "a" for p in picks) <= 4  # 30% of 15 names
    assert len(picks) == 15


def test_failed_sector_lookup_keeps_full_book():
    names = [f"T{i}" for i in range(40)]
    score = pd.Series(np.arange(40, 0, -1.0), index=names)
    assert len(book.select(score, pd.Series("all", index=names), held=[])) == 15


def test_weights_sum_and_earnings_cap():
    picks = [f"T{i}" for i in range(15)]
    dtr = pd.Series([5.0] * 3 + [60.0] * 12, index=picks)
    w = book.weights(picks, dtr)
    assert w.sum() == pytest.approx(1.0)
    assert (w[:3] <= 0.06 + 1e-9).all() and (w <= 0.10 + 1e-9).all() and (w >= 0).all()


def test_backtest_has_no_lookahead(ds):
    cfg = model.load_config()
    start, end = pd.Timestamp("2021-01-04"), pd.Timestamp("2021-06-30")
    inp = pipeline.load(ds, start.date(), end.date())
    dates = inp.close.index
    sig = [dates[i - 1] for i in sim.rebalance_days(dates)] + [dates[dates.searchsorted(start) - 1]]
    sv = data.load_state_vector(ds, (start - pd.Timedelta(days=20)).date(), end.date(), sig)

    def run(c, s):
        return sim.run(c, inp.volume, s, model.strategy(inp.groups, cfg), start, end)

    base = run(inp.close, sv)
    cut = pd.Timestamp("2021-04-01")
    close2 = inp.close.copy()
    after = close2.index >= cut
    close2.loc[after] *= np.random.default_rng(1).uniform(0.5, 1.5, close2.loc[after].shape)
    sv2 = sv.copy()
    sv2.loc[sv2["date"] >= cut, "guidance_range_velocity"] *= -1
    alt = run(close2, sv2)
    b1, b2 = base["books"], alt["books"]
    pd.testing.assert_frame_equal(b1[b1["date"] < cut], b2[b2["date"] < cut])
    assert not b1[b1["date"] >= cut].equals(b2[b2["date"] >= cut])  # the change did bite later
    before = slice(None, cut - pd.Timedelta(days=1))
    pd.testing.assert_frame_equal(base["daily"].loc[before], alt["daily"].loc[before])


def test_live_book_is_valid(ds):
    from nabla import live
    b = live.build_book(ds, model.load_config())
    w = [h["weight"] for h in b["holdings"]]
    assert len(w) == 15 and abs(sum(w) - 1) < 1e-6 and min(w) >= 0
    assert {h["ticker"] for h in b["holdings"]} <= set(ds.universe())
    assert b["as_of"] == str(data.last_trading_day(ds))


def test_api_shapes(root, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as m
    monkeypatch.setattr(m, "BOOK", tmp_path / "book.json")  # no frozen book: fallback path
    monkeypatch.setattr(m, "_maybe_refresh", lambda book: None)
    c = TestClient(m.app)
    assert c.get("/health").json()["ok"] is True
    h = c.get("/portfolio/holdings").json()
    assert abs(sum(x["weight"] for x in h["holdings"]) - 1) < 0.01
    r = c.post("/backtest", json={"tickers": ["AAPL", "MSFT"], "weights": [0.5, 0.5],
                                  "start": "2020-01-02", "end": "2020-12-31"}).json()
    assert {"n_days", "total_return", "sharpe", "max_drawdown"} <= set(r)
    rows = c.get("/asof", params={"ticker": "AAPL", "on": "2024-03-31"}).json()
    assert all(str(x["date"])[:10] <= "2024-03-31" for x in rows)


def test_return_clusters_recover_planted_groups():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2020-01-01", periods=300)
    f = rng.normal(0, 0.02, (300, 3))
    cols, series = [], []
    for g in range(3):
        for i in range(12):
            cols.append(f"G{g}_{i}")
            series.append(f[:, g] + rng.normal(0, 0.005, 300))
    close = pd.DataFrame(100 * np.cumprod(1 + np.array(series).T, axis=0), index=idx, columns=cols)
    lab = data.return_clusters(close, k=3)
    for g in range(3):
        assert lab[[c for c in cols if c.startswith(f"G{g}_")]].nunique() == 1
    assert lab.nunique() == 3


def test_cash_sleeve():
    w = book.with_cash(pd.Series({"A": 0.4, "B": 0.35}))
    assert w["CASHHOLDING"] == pytest.approx(0.25) and w.sum() == pytest.approx(1.0)
    assert "CASHHOLDING" not in book.with_cash(pd.Series({"A": 0.5, "B": 0.5}))
    from nabla import costs
    ft = pd.DataFrame({"adv20": [1e8, 1e8], "price": [10.0, 10.0], "momentum": [0.1, 0.1],
                       "amihud": [0.01, 0.01]}, index=["A", "B"])
    assert costs.trade_cost(pd.Series({"CASHHOLDING": 0.5}), ft, 1e6) == 0.0


def test_year_cache_reuses_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "CACHE", tmp_path)
    calls = []

    def fetch(a, b):
        calls.append((a, b))
        d = pd.bdate_range(a, b)
        return pd.DataFrame({"ticker": "A", "date": d, "close": 1.0, "volume": 1.0})

    from datetime import date
    x = data._cached_years("prices", date(2022, 6, 1), date(2023, 3, 31), fetch)
    assert x["date"].min() >= pd.Timestamp("2022-06-01") and x["date"].max() <= pd.Timestamp("2023-03-31")
    n = len(calls)
    data._cached_years("prices", date(2022, 6, 1), date(2023, 3, 31), fetch)
    assert len(calls) == n  # second run reads disk only


def test_no_trade_band():
    prev = pd.Series({"A": 0.27, "B": 0.33, "C": 0.40})
    target = pd.Series({"A": 0.26, "B": 0.24, "D": 0.50})
    out = book.no_trade(prev, target, 0.02)
    assert out["A"] == pytest.approx(0.27)          # moved < 2 points: untouched
    assert "C" not in out and out.sum() == pytest.approx(1.0)
    assert out["B"] < 0.33                          # moved > 2 points: traded
    assert book.no_trade(pd.Series(dtype=float), target).equals(target)


def test_api_decide(root, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as m
    c = TestClient(m.app)
    r = c.post("/decide", json={"information_cutoff": "2025-06-06"}).json()
    assert r["action"] == "rebalance" and abs(sum(h["weight"] for h in r["target_holdings"]) - 1) < 1e-6
    assert c.get("/decide", params={"information_cutoff": "2025-06-04"}).json()["action"] == "hold"


def _small_run(ds, **kw):
    cfg = model.load_config()
    start, end = pd.Timestamp("2021-01-04"), pd.Timestamp("2021-03-31")
    inp = pipeline.load(ds, start.date(), end.date())
    dates = inp.close.index
    sig = [dates[i - 1] for i in sim.rebalance_days(dates)] + [dates[dates.searchsorted(start) - 1]]
    sv = data.load_state_vector(ds, (start - pd.Timedelta(days=20)).date(), end.date(), sig)
    return inp, sim.run(inp.close, inp.volume, sv, model.strategy(inp.groups, cfg), start, end, **kw)


def test_open_fill_equal_to_close_matches_default(ds):
    inp, base = _small_run(ds)
    _, same = _small_run(ds, open_=inp.close)  # open == close: trading at the open is trading at the close
    pd.testing.assert_series_equal(base["daily"]["ret"], same["daily"]["ret"], atol=1e-12)


def test_open_fill_at_prior_close_gives_new_book_the_whole_day(ds):
    inp, base = _small_run(ds)
    _, early = _small_run(ds, open_=inp.close.shift(1))  # open == prior close
    reb = base["books"]["date"]
    # same names chosen (signals do not depend on fills); returns differ on trade days
    assert [sorted(w) for w in base["books"]["weights"]] == [sorted(w) for w in early["books"]["weights"]]
    assert not np.allclose(base["daily"].loc[reb, "ret"], early["daily"].loc[reb, "ret"])


def test_api_decide_fallback_when_over_budget(root, monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as m
    from nabla import decide as dc
    monkeypatch.setattr(m, "DECIDE_BUDGET_SECONDS", 0.0)
    dc._BOOKS.clear()
    r = TestClient(m.app).post("/decide", json={"information_cutoff": "2024-03-01"}).json()
    assert abs(sum(h["weight"] for h in r["target_holdings"]) - 1) < 0.01
    assert "decision_id" in r
