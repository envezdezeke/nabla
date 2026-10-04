"""Return-variant inputs (beta, post-earnings drift) and the significance tests."""
import numpy as np
import pandas as pd

from nabla import factors, fundamentals as F, stats


def _quarters(n=14):
    return pd.date_range("2021-03-31", periods=n, freq="QE")


def test_sue_uses_same_quarter_last_year_and_past_changes_only():
    pe = _quarters()
    eps = [1.0, 1.1, 1.2, 1.3, 1.1, 1.2, 1.25, 1.4, 1.15, 1.3, 1.3, 1.5, 1.2, 2.5]
    f = pd.DataFrame({"ticker": "AAA", "date": pe, "eps": eps})
    f["knowable"] = f["date"] + pd.Timedelta(days=40)
    s = F.sue(f)
    d = pd.Series(eps) - pd.Series(eps).shift(4)
    expect = d.iloc[-1] / d.iloc[4:-1].tail(8).std()
    assert np.isclose(s.iloc[-1], expect)
    assert s.iloc[-1] > 3  # the jump to 2.5 is a big positive surprise
    assert s.iloc[:8].isna().all()  # needs four earlier changes


def test_pead_is_neutral_before_filing_and_after_it_goes_stale():
    pe = _quarters()
    f = pd.DataFrame({"ticker": "AAA", "date": pe, "eps": np.linspace(1, 2, len(pe)) + [0, .1] * 7})
    f["knowable"] = f["date"] + pd.Timedelta(days=40)
    f["sue"] = F.sue(f)
    last = f["knowable"].iloc[-1]
    assert F.pead(f, last + pd.Timedelta(days=1))["AAA"] == f["sue"].iloc[-1]
    before = F.pead(f, last - pd.Timedelta(days=1))  # previous quarter's surprise
    assert before["AAA"] == f["sue"].iloc[-2]
    assert "AAA" not in F.pead(f, last + pd.Timedelta(days=120)).index


def test_beta_ranks_a_levered_name_above_a_defensive_one():
    rng = np.random.default_rng(0)
    m = rng.normal(0, 0.01, 260)
    rets = pd.DataFrame({"HI": 1.6 * m + rng.normal(0, .005, 260), "LO": 0.4 * m + rng.normal(0, .005, 260),
                         "MID": m + rng.normal(0, .005, 260)})
    close = 100 * (1 + rets).cumprod()
    ft = factors.price_features(close, pd.DataFrame(1e6, index=close.index, columns=close.columns))
    assert ft.loc["HI", "beta"] > ft.loc["MID", "beta"] > ft.loc["LO", "beta"]
    assert abs(ft["beta"].mean() - 1) < 0.05  # shrunk toward 1 and centered on the market


def test_newey_west_and_bootstrap_see_a_real_edge_and_miss_noise():
    rng = np.random.default_rng(1)
    base = pd.Series(rng.normal(0.0004, 0.01, 1500))
    good = base + rng.normal(0.0004, 0.002, 1500)  # +10%/yr with tracking error 3%
    noise = base + rng.normal(0.0, 0.002, 1500)
    assert stats.newey_west_t(good - base) > 3
    g = stats.paired_bootstrap(good, base, n_boot=300)
    n = stats.paired_bootstrap(noise, base, n_boot=300)
    assert g["p_gap_le_0"] < 0.01 and n["p_gap_le_0"] > 0.05


def test_deflated_sharpe_falls_with_more_trials():
    rng = np.random.default_rng(2)
    r = pd.Series(rng.normal(0.0004, 0.01, 1500))
    one = stats.deflated_sharpe(r, 1)["dsr"]
    many = stats.deflated_sharpe(r, 50)["dsr"]
    assert many < one


def test_rebalance_offsets_and_frequency():
    from nabla import sim
    dates = pd.bdate_range("2024-01-01", "2024-03-29")
    base = sim.rebalance_days(dates)
    assert sim.rebalance_days(dates, 0, 1) == base
    tue = sim.rebalance_days(dates, 1)
    assert all(dates[i].weekday() == 1 for i in tue)
    every2 = sim.rebalance_days(dates, 0, 2)
    assert set(every2) <= set(base) and abs(len(every2) - len(base) / 2) <= 1
    assert set(sim.rebalance_days(dates, 0, 4)) <= set(base) | {0}


def test_beta_limit_swaps_highest_beta_for_best_ranked_low_beta():
    from nabla import book
    names = [f"N{i}" for i in range(8)]
    score = pd.Series(np.linspace(1, 0, 8), index=names)
    beta = pd.Series([2.0, 1.0, 1.0, 1.0, 2.5, 0.8, 0.7, 1.5], index=names)
    groups = pd.Series("all", index=names)
    weigh = lambda p: pd.Series(1 / len(p), index=p)  # noqa: E731
    w = book.beta_limit(weigh(names[:4]), score, groups, beta, weigh, 1.2, pool_size=8, n=4)
    assert set(w.index) == {"N1", "N2", "N3", "N5"}  # N0 (beta 2) out, N5 (best low-beta) in
    assert (w * beta[w.index]).sum() <= 1.2
    same = book.beta_limit(weigh(names[1:4]), score, groups, beta, weigh, 1.2, pool_size=8, n=4)
    assert list(same.index) == names[1:4]
    stressed = book.beta_limit(weigh(names[:4]), score, groups, beta, weigh, 1.2, invested=0.75, pool_size=8, n=4)
    assert list(stressed.index) == names[:4]  # 1.25 x 0.75 is under the cap: no swap
