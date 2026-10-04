"""Stress/panic flags: on in a crash, off in calm markets, hysteresis, no look-ahead."""
import numpy as np
import pandas as pd

from nabla import regime


def _spx():
    idx = pd.bdate_range("2015-01-01", "2021-12-31")
    rng = np.random.default_rng(0)
    r = rng.normal(0.0006, 0.004, len(idx))   # steady uptrend: calm outside the crash
    crash = (idx >= "2020-02-20") & (idx <= "2020-03-23")
    r[crash] = rng.normal(-0.012, 0.04, crash.sum())   # sharp, volatile drop
    return pd.Series(4000 * np.cumprod(1 + r), index=idx)


def test_stress_on_in_crash_off_in_calm():
    w = regime.weekly_flags(_spx())
    assert w.loc["2020-03-01":"2020-04-10", "stress"].any()
    assert not w.loc["2017-01-01":"2017-12-31", "stress"].any()


def test_flag_needs_two_calm_weeks_to_turn_off():
    w = regime.weekly_flags(_spx())
    s = w["stress"].astype(int).diff()
    offs = s[s == -1].index
    for d in offs:
        prev = w.loc[:d].iloc[-3:-1]   # the two checks before switching off
        assert prev["stress"].all()


def test_flags_asof_uses_only_past_data():
    spx = _spx()
    a = regime.flags_asof(spx, "2020-03-13")
    b = regime.flags_asof(spx[spx.index <= "2020-03-13"], "2020-03-13")
    assert a == b


def test_flags_at_and_decide_regime():
    import pandas as pd
    from nabla import model, regime
    wf = pd.DataFrame({"stress": [False, True], "panic": [False, True]},
                      index=pd.to_datetime(["2022-01-07", "2022-01-14"]))
    assert regime.flags_at(wf, "2022-01-13") == {"stress": False, "panic": False}
    assert regime.flags_at(wf, "2022-01-14") == {"stress": True, "panic": True}
    assert regime.flags_at(None, "2022-01-14")["stress"] is False
    names = [f"T{i}" for i in range(40)]
    ft = pd.DataFrame({"price": 50.0, "adv20": 1e8, "amihud": 0.01, "momentum": range(40),
                       "guidance_velocity": 0.0, "quality": 0.0, "value": 0.0, "vol_premium": 0.0,
                       "days_to_next_report": 60.0, "rv21": 0.3}, index=names)
    cfg = model.load_config()
    cfg["regime"] = {"panic_momentum": True, "stress_cash": 0.25}
    w_calm, _ = model.decide(ft, pd.Series("g", index=names), [], cfg, {"stress": False, "panic": False})
    w_stress, _ = model.decide(ft, pd.Series("g", index=names), [], cfg, {"stress": True, "panic": True})
    assert abs(w_calm.sum() - 1) < 1e-9 and abs(w_stress.sum() - 0.75) < 1e-9
