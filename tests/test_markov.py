import numpy as np
import pandas as pd

from nabla import markov, regime


def _spx(seed=0):
    """Calm 0.7%/day vol with two stress spells at 2.5%/day."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2016-01-04", "2021-12-31")
    vol = np.full(len(idx), 0.007)
    stress = ((idx >= "2018-10-01") & (idx < "2018-12-31")) | ((idx >= "2020-02-24") & (idx < "2020-05-01"))
    vol[stress] = 0.025
    drift = np.where(stress, -0.002, 0.0005)
    return pd.Series(3000 * np.cumprod(1 + drift + rng.normal(0, 1, len(idx)) * vol), index=idx), stress


def test_recovers_regimes_and_orders_states():
    spx, stress = _spx()
    p = markov.fit(spx.pct_change().dropna())
    d = markov.describe(p)
    assert d["stress_vol"] > 2.5 * d["calm_vol"]          # state 1 is the volatile one
    assert d["calm_days"] > 20 and d["stress_days"] > 5    # persistent regimes
    ps = markov.filtered(spx.pct_change().dropna(), p)
    s = pd.Series(stress, index=spx.index).reindex(ps.index)
    assert ps[s].mean() > 0.7 and ps[~s].mean() < 0.15


def test_filter_has_no_lookahead():
    spx, _ = _spx()
    params = markov.fit_yearly(spx, [2019, 2020, 2021])
    a = markov.p_stress(spx, params)
    cut = pd.Timestamp("2020-03-02")
    later = spx.copy()
    later[later.index > cut] *= np.random.default_rng(5).uniform(0.7, 1.3, (later.index > cut).sum())
    b = markov.p_stress(later, markov.fit_yearly(later, [2019, 2020, 2021]))
    pd.testing.assert_series_equal(a[a.index <= cut], b[b.index <= cut])


def test_fit_is_deterministic():
    spx, _ = _spx()
    r = spx.pct_change().dropna()
    a, b = markov.fit(r), markov.fit(r)
    assert np.array_equal(a["A"], b["A"]) and np.array_equal(a["sd"], b["sd"])


def test_yearly_fits_use_only_prior_data():
    spx, _ = _spx()
    a = markov.fit_yearly(spx, [2020])[2020]
    b = markov.fit_yearly(spx[spx.index < "2020-01-01"], [2020])[2020]
    assert np.allclose(a["sd"], b["sd"]) and np.allclose(a["A"], b["A"])


def test_weekly_table_methods_and_hysteresis():
    spx, _ = _spx()
    params = markov.fit_yearly(spx, [2018, 2019, 2020, 2021])
    for m in regime.METHODS:
        w = regime.weekly_table(spx, {"method": m}, params)
        assert {"stress", "panic", "p_stress"} <= set(w.columns)
    hmm = regime.weekly_table(spx, {"method": "hmm"}, params)
    assert hmm.loc["2020-03-01":"2020-04-15", "stress"].all()     # flags the 2020 spell
    assert hmm.loc["2021-03-01":"2021-12-31", "stress"].mean() < 0.1  # quiet when calm
    w = pd.DataFrame({"p": [0.9, 0.6, 0.4, 0.4, 0.4]}, index=pd.bdate_range("2020-01-03", periods=5, freq="W-FRI"))
    f = regime._hmm_flags(w, "p", None, regime.HMM_DEFAULTS)
    assert list(f) == [True, True, True, False, False]  # off only after two checks below 0.5
