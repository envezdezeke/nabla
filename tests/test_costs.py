"""Liquidity filter and trading-cost model."""
import numpy as np
import pandas as pd

from nabla import costs, factors

LIQ = {"min_adv": 50e6, "min_price": 5.0, "amihud_drop_pct": 0.90}


def _ft(n=40, seed=0):
    rng = np.random.default_rng(seed)
    adv = np.linspace(60e6, 2e9, n)
    return pd.DataFrame({
        "price": np.full(n, 50.0), "momentum": rng.normal(size=n), "adv20": adv,
        "amihud": 1e6 / adv * 0.02,  # thinner names move more per dollar
    }, index=[f"S{i:02d}" for i in range(n)])


def test_filter_applies_adv_price_and_drops_least_liquid_tenth():
    ft = _ft()
    ft.loc["S00", "adv20"] = 10e6           # too little volume
    ft.loc["S01", "price"] = 3.0            # penny stock
    ft.loc["S02", "amihud"] = np.nan        # unknown liquidity
    ok = factors.liquid(ft, **LIQ)
    assert not ok[["S00", "S01", "S02"]].any()
    survivors = ft.index[(ft["adv20"] >= 50e6) & (ft["price"] > 5) & ft["amihud"].notna()]
    assert ok.sum() == int(np.floor(len(survivors) * 0.9)) or ok.sum() == int(np.ceil(len(survivors) * 0.9))
    dropped = survivors.difference(ft.index[ok])
    assert ft.loc[dropped, "amihud"].min() >= ft.loc[ok, "amihud"].max()   # the least liquid go
    rep = factors.liquidity_report(ft, **LIQ)
    assert rep["after_adv"] == 39 and rep["after_price"] == 38 and rep["after_amihud"] == int(ok.sum())


def test_half_spread_tiers_follow_dollar_volume():
    ft = _ft()
    h = costs.half_spread(ft, LIQ) * 1e4
    ok = factors.liquid(ft, **LIQ)
    assert set(h[ok].round(6)) == {5.0, 10.0, 20.0}
    assert h[ft["adv20"].idxmax()] == 5.0
    assert (h[~ok] == 20.0).all()          # names we can only sell pay the top tier


def test_cost_has_spread_plus_impact_that_grows_with_size():
    ft = _ft()
    name = ft.index[5]
    small = costs.trade_cost(pd.Series({name: 0.01}), ft, 1e6, LIQ)
    big = costs.trade_cost(pd.Series({name: 0.02}), ft, 1e6, LIQ)
    h = float(costs.half_spread(ft, LIQ)[name])
    imp_small = small - 0.01 * h
    assert imp_small > 0
    assert np.isclose(big - 0.02 * h, 4 * imp_small)   # impact scales with size squared
    assert costs.trade_cost(pd.Series({name: 0.0}), ft, 1e6, LIQ) == 0.0
    # selling costs the same as buying
    assert np.isclose(costs.trade_cost(pd.Series({name: -0.01}), ft, 1e6, LIQ), small)


def test_realistic_size_costs_a_few_bps():
    ft = _ft()
    full = pd.Series(1 / 15, index=ft.index[-15:])      # build a 15-name book in liquid names
    c = costs.trade_cost(full, ft, 1e6, LIQ)
    assert 0 < c < 0.002                                  # well under 20 bps of the book


def test_adv_cap_limits_position_to_one_percent_of_volume():
    ft = _ft()
    cap = costs.adv_cap(ft, 1e6)
    assert np.isclose(cap.iloc[0], 0.01 * 60e6 / 1e6)
