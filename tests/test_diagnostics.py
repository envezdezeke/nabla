"""Five-bucket factor test: verdicts on planted good, backwards, noise and leaky factors."""
import numpy as np
import pandas as pd

from nabla import diagnostics as D


def _panel(effect, n_dates=48, n=300, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2019-01-31", periods=n_dates, freq="ME")
    names = [f"S{i}" for i in range(n)]
    z_by, fwd = {}, {}
    for d in dates:
        z = pd.Series(rng.normal(size=n), index=names)
        fwd[d] = effect * z + rng.normal(0, 0.08, n)
        z_by[d] = z
    return z_by, pd.DataFrame(fwd, index=names).T


def test_good_factor_passes():
    r = D.summarize(D.quintile_table(*_panel(0.004)))
    assert r["flags"] == ["ok"] and r["q5_minus_q1"] > 0 and r["monotonic"] >= 0.8


def test_backwards_factor_is_flagged():
    r = D.summarize(D.quintile_table(*_panel(-0.004)))
    assert "backwards" in r["flags"]


def test_huge_returns_are_flagged_as_possible_leak():
    r = D.summarize(D.quintile_table(*_panel(0.05)))
    assert "too_good" in r["flags"]


def test_noise_is_not_called_ok_reliably():
    r = D.summarize(D.quintile_table(*_panel(0.0, seed=3)))
    assert r["flags"] != ["ok"] or abs(r["spread_t"]) < 2


def test_forward_returns_skip_a_day():
    idx = pd.bdate_range("2024-01-01", periods=30)
    close = pd.DataFrame({"A": np.arange(1, 31, dtype=float)}, index=idx)
    f = D.forward_returns(close, [idx[0]], horizon=5, skip=1)
    assert np.isclose(f.loc[idx[0], "A"], close["A"].iloc[6] / close["A"].iloc[1] - 1)
