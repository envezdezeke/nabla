import numpy as np
import pandas as pd
from nabla import backtest, combine, factors, portfolio, synthetic


def _data():
    return synthetic.make_universe()


def test_momentum_has_no_lookahead():
    d = _data()
    p = d["prices"]
    m = factors.momentum_12_1(p)
    t = 400
    m2 = factors.momentum_12_1(p.iloc[: t + 1])
    pd.testing.assert_series_equal(m.iloc[t], m2.iloc[t])


def test_caps_respected():
    d = _data()
    score = pd.Series(np.random.default_rng(1).normal(size=60), index=d["prices"].columns)
    w = portfolio.apply_caps(portfolio.top_n_weights(score, n=30), d["sectors"])
    assert w.max() <= portfolio.MAX_POSITION + 1e-9
    assert (w.groupby(d["sectors"].reindex(w.index)).sum() <= portfolio.SECTOR_CAP + 1e-9).all()
    assert w.sum() <= 1 + 1e-9


def test_end_to_end_backtest_runs():
    d = _data()
    p, sec = d["prices"], d["sectors"]
    f = {
        "momentum": factors.momentum_12_1(p),
        "reversal": factors.short_term_reversal(p),
        "low_vol": factors.low_volatility(p),
        "revisions": factors.estimate_revisions(factors.lag_fundamentals(d["fwd_eps"], 1)),
        "quality": factors.quality(factors.lag_fundamentals(d["roe"]), factors.lag_fundamentals(d["d2e"])),
        "value": factors.value(factors.lag_fundamentals(d["pe"])),
    }
    comp = combine.composite(f, sec)

    def weights_fn(date):
        w = portfolio.top_n_weights(comp.loc[date], n=30)
        return portfolio.apply_caps(w, sec)

    res = backtest.backtest(p, weights_fn)
    s = backtest.stats(res)
    assert np.isfinite(s["total_return"]) and res["equity"].notna().all()
